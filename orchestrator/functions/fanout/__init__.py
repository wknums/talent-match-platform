"""Batch fan-out orchestrator + supporting activities (Service Bus dispatch).

Flow
====
1. ``batch_orchestrator`` receives the batch payload.
2. ``prepare_prompt_blob`` activity writes the inline prompt to
   ``batch-results/{batchId}/prompt.txt`` and returns the blob URI.
3. For each (CV × run), the orchestrator:
      - mints a deterministic ``run_id`` (uuid5(batch_id, "{app}:{idx}")),
      - calls ``dispatch_run`` activity which writes a run-index blob
        ``batch-results/{batchId}/run-index/{run_id}.json`` and publishes a
        ``RunMessage`` to the ``engine-runs`` Service Bus queue,
      - awaits an external event named ``run-{run_id}`` raised by the
        ``result_intake`` blueprint when the engine returns a result.
4. ``task_any`` collects per-run results one at a time so Durable custom status
    can advance as results arrive.
5. ``finalize_batch`` aggregates per-CV results and writes
   ``batches/{batchId}/result.json`` to the ``BLOB_RESULTS_CONTAINER``.

The platform does **not** call the engine over HTTP. The engine is the
queue-worker wrapper consuming ``engine-runs`` and reporting back via
``engine-results`` (Service Bus) or ``PATCH /runs/{run_id}`` (HTTP).
"""

import json
import logging
import hashlib
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import azure.durable_functions as df  # type: ignore[import-untyped]
import azure.functions as func
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.storage.blob import BlobClient, BlobServiceClient

from orchestrator.engine_contracts import (
    BatchPayload,
    DispatchRunInput,
    FinalizeBatchInput,
)
from orchestrator.sb_contracts import RunMessage, RunParameters
from runtime.config import get_settings
from runtime.events import build_live_progress_event, project_live_progress_event
from runtime.aggregation import AGGREGATION_PROFILE_CV, aggregate_run_outputs
from runtime.telemetry import log_lifecycle_event

logger = logging.getLogger(__name__)

bp = df.Blueprint()

_ORCHESTRATOR_NAME = "batch_orchestrator"

# Fixed namespace for deterministic run_id derivation. Any UUID works; do not
# change once in production — would break replay idempotency.
_RUN_ID_NAMESPACE = uuid.UUID("6b8b4567-8e07-4a4f-9d2c-1234567890ab")


def _mint_run_id(batch_id: str, application_id: str, run_index: int) -> str:
    return str(uuid.uuid5(_RUN_ID_NAMESPACE, f"{batch_id}:{application_id}:{run_index}"))


def _build_initial_progress(
    *,
    batch_id: str,
    job_id: str,
    cvs: list[dict[str, Any]],
    run_count: int,
    updated_at: str,
) -> dict[str, Any]:
    applications: list[dict[str, Any]] = []
    for cv in cvs:
        runs = []
        for run_index in range(run_count):
            runs.append(
                {
                    "runId": _mint_run_id(batch_id, cv["applicationId"], run_index),
                    "runIndex": run_index,
                    "status": "queued",
                    "dispatchedAt": None,
                    "completedAt": None,
                    "artifactCount": 0,
                    "artifactNames": [],
                    "errorMessage": None,
                }
            )
        applications.append(
            {
                "applicationId": cv["applicationId"],
                "documentId": cv["documentId"],
                "status": "queued",
                "runsCompleted": 0,
                "runsTotal": run_count,
                "lastUpdatedAt": updated_at,
                "runs": runs,
            }
        )

    return {
        "submissionId": batch_id,
        "batchId": batch_id,
        "jobId": job_id,
        "status": "queued",
        "cvsCompleted": 0,
        "cvsTotal": len(cvs),
        "runsCompleted": 0,
        "runsDispatched": 0,
        "runsTotal": len(cvs) * run_count,
        "lastUpdatedAt": updated_at,
        "applications": applications,
    }


def _record_dispatched_run(progress: dict[str, Any], *, run_id: str, updated_at: str) -> None:
    match = _find_application_run(progress, run_id)
    if match is None:
        return

    application, run = match
    if run.get("status") == "queued":
        progress["runsDispatched"] += 1
    run["status"] = "dispatched"
    run["dispatchedAt"] = updated_at
    application["status"] = "running"
    application["lastUpdatedAt"] = updated_at
    progress["status"] = "running"
    progress["lastUpdatedAt"] = updated_at


def _record_run_result(
    progress: dict[str, Any], *, run_result: dict[str, Any], updated_at: str
) -> None:
    run_id = run_result.get("run_id")
    if not run_id:
        return

    match = _find_application_run(progress, run_id)
    if match is None:
        return

    application, run = match
    was_terminal = _is_terminal_run_status(run.get("status"))
    if was_terminal:
        logger.info("duplicate terminal run result ignored run_id=%s", run_id)
        return

    artifacts = run_result.get("artifacts") or []
    run["status"] = run_result.get("status")
    run["durationMs"] = run_result.get("duration_ms")
    run["tokensPrompt"] = run_result.get("tokens_prompt")
    run["tokensCompletion"] = run_result.get("tokens_completion")
    run["correlationId"] = run_result.get("correlation_id")
    run["traceparent"] = run_result.get("traceparent")
    run["artifacts"] = artifacts
    run["artifactCount"] = len(artifacts)
    run["artifactNames"] = [artifact.get("name") for artifact in artifacts if artifact.get("name")]
    run["errorMessage"] = run_result.get("error_message")
    run["completedAt"] = updated_at

    progress["runsCompleted"] += 1
    application["runsCompleted"] += 1

    log_lifecycle_event(
        stage="orchestrator.run_result",
        status=str(run_result.get("status") or ""),
        batch_id=str(progress.get("batchId") or ""),
        run_id=str(run_id),
        application_id=str(application.get("applicationId") or ""),
        correlation_id=str(run_result.get("correlation_id") or ""),
        traceparent=str(run_result.get("traceparent") or ""),
    )

    application["status"] = _summarize_application_status(application["runs"])
    application["lastUpdatedAt"] = updated_at
    if _is_application_terminal(application):
        completed_ids = {
            app["applicationId"]
            for app in progress["applications"]
            if _is_application_terminal(app)
        }
        progress["cvsCompleted"] = len(completed_ids)
    progress["status"] = "running"
    progress["lastUpdatedAt"] = updated_at


def _find_application_run(
    progress: dict[str, Any], run_id: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for application in progress.get("applications", []):
        for run in application.get("runs", []):
            if run.get("runId") == run_id:
                return application, run
    return None


def _is_terminal_run_status(status: Any) -> bool:
    return _status_key(status) in {"succeeded", "completed", "failed", "cancelled", "canceled"}


def _is_application_terminal(application: dict[str, Any]) -> bool:
    return all(_is_terminal_run_status(run.get("status")) for run in application.get("runs", []))


def _summarize_application_status(runs: list[dict[str, Any]]) -> str:
    statuses = [_status_key(run.get("status")) for run in runs]
    if any(status in {"queued", "dispatched", "running", ""} for status in statuses):
        return "running" if any(status != "queued" for status in statuses) else "queued"
    unique_statuses = set(statuses)
    if unique_statuses <= {"succeeded", "completed"}:
        return "completed"
    if unique_statuses <= {"failed"}:
        return "failed"
    if unique_statuses <= {"cancelled", "canceled"}:
        return "cancelled"
    return "partial"


def _status_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _build_run_completed_live_event(
    *,
    progress: dict[str, Any],
    occurred_at: str,
    sequence: int,
    default_correlation_id: str,
    default_traceparent: str,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    return build_live_progress_event(
        event_type="run.completed",
        progress=progress,
        occurred_at=occurred_at,
        sequence=sequence,
        correlation_id=str(run_result.get("correlation_id") or default_correlation_id),
        traceparent=str(run_result.get("traceparent") or default_traceparent),
        run_id=run_result["run_id"],
        artifacts=run_result.get("artifacts") or [],
    )


def _build_run_terminal_live_event(
    *,
    progress: dict[str, Any],
    occurred_at: str,
    sequence: int,
    default_correlation_id: str,
    default_traceparent: str,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    event_type = _terminal_run_event_type(run_result.get("status"))
    return build_live_progress_event(
        event_type=event_type,
        progress=progress,
        occurred_at=occurred_at,
        sequence=sequence,
        correlation_id=str(run_result.get("correlation_id") or default_correlation_id),
        traceparent=str(run_result.get("traceparent") or default_traceparent),
        run_id=run_result["run_id"],
        artifacts=run_result.get("artifacts") or [],
    )


def _build_application_terminal_live_event(
    *,
    progress: dict[str, Any],
    occurred_at: str,
    sequence: int,
    correlation_id: str,
    traceparent: str,
    application_id: str,
) -> dict[str, Any]:
    application = _find_application(progress, application_id)
    if application is None:
        raise KeyError(f"application {application_id} not found")

    terminal_run = next((run for run in application.get("runs", []) if run.get("runId")), None)
    return build_live_progress_event(
        event_type="application.completed",
        progress=progress,
        occurred_at=occurred_at,
        sequence=sequence,
        correlation_id=correlation_id,
        traceparent=traceparent,
        run_id=(terminal_run or {}).get("runId"),
    )


def _build_batch_terminal_live_event(
    *,
    progress: dict[str, Any],
    occurred_at: str,
    sequence: int,
    correlation_id: str,
    traceparent: str,
) -> dict[str, Any]:
    return build_live_progress_event(
        event_type="batch.cancelled" if _is_cancelled_batch(progress) else "batch.completed",
        progress=progress,
        occurred_at=occurred_at,
        sequence=sequence,
        correlation_id=correlation_id,
        traceparent=traceparent,
    )


def _build_batch_state_live_event(
    *,
    instance_id: str,
    status_obj: Any,
    status: str,
    event_type: str,
    occurred_at: str,
    correlation_id: str,
    traceparent: str,
) -> dict[str, Any]:
    progress = _progress_for_status_event(
        instance_id=instance_id,
        status_obj=status_obj,
        status=status,
        occurred_at=occurred_at,
    )
    return build_live_progress_event(
        event_type=event_type,
        progress=progress,
        occurred_at=occurred_at,
        sequence=_next_event_sequence(progress),
        correlation_id=correlation_id,
        traceparent=traceparent,
    )


def _coerce_run_result_payload(value: Any) -> dict[str, Any]:
    """Normalize external event payload to a dict.

    Durable external events can arrive as already-decoded dicts or JSON strings
    depending on transport/runtime serialization behavior.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("run result payload is not valid JSON") from exc
        if isinstance(parsed, dict):
            return parsed
    raise TypeError("run result payload must be a dict")


def _terminal_run_event_type(status: Any) -> str:
    status_key = _status_key(status)
    if status_key == "failed":
        return "run.failed"
    if status_key in {"cancelled", "canceled"}:
        return "run.cancelled"
    return "run.completed"


def _find_application(progress: dict[str, Any], application_id: str) -> dict[str, Any] | None:
    for application in progress.get("applications", []):
        if application.get("applicationId") == application_id:
            return application
    return None


def _is_cancelled_batch(progress: dict[str, Any]) -> bool:
    applications = progress.get("applications", [])
    if not applications:
        return False
    return all(_status_key(application.get("status")) in {"cancelled", "canceled"} for application in applications)


def _progress_for_status_event(
    *,
    instance_id: str,
    status_obj: Any,
    status: str,
    occurred_at: str,
) -> dict[str, Any]:
    if isinstance(getattr(status_obj, "custom_status", None), dict):
        progress = dict(status_obj.custom_status)
        progress["applications"] = [dict(app) for app in progress.get("applications", [])]
    else:
        progress = {
            "submissionId": instance_id,
            "batchId": instance_id,
            "jobId": None,
            "cvsCompleted": 0,
            "cvsTotal": 0,
            "runsCompleted": 0,
            "runsDispatched": 0,
            "runsTotal": 0,
            "applications": [],
        }
    progress["submissionId"] = progress.get("submissionId") or instance_id
    progress["batchId"] = progress.get("batchId") or instance_id
    progress["status"] = status
    progress["lastUpdatedAt"] = occurred_at
    return progress


def _next_event_sequence(progress: dict[str, Any]) -> int:
    terminal_applications = sum(
        1 for application in progress.get("applications", []) if _is_application_terminal(application)
    )
    return int(progress.get("runsDispatched") or 0) + int(progress.get("runsCompleted") or 0) + terminal_applications + 1


# ── Orchestrator ─────────────────────────────────────────────────────────────
@bp.orchestration_trigger(context_name="context")
def batch_orchestrator(context):
    raw = context.get_input() or {}
    payload = BatchPayload.model_validate(raw)
    batch_id = payload.batch_id
    cvs = payload.cvs
    run_count = payload.run_count
    prompt_text = (payload.prompt or {}).get("text", "")
    correlation_id = raw.get("correlationId") or raw.get("correlation_id") or ""
    traceparent = raw.get("traceparent") or ""

    progress = _build_initial_progress(
        batch_id=batch_id,
        job_id=payload.job_id,
        cvs=cvs,
        run_count=run_count,
        updated_at=context.current_utc_datetime.isoformat(),
    )
    context.set_custom_status(progress)
    event_sequence = 0
    emitted_application_events: set[str] = set()

    # 1) Stage the inline prompt to blob (engine consumes by URI).
    prompt_blob_uri = yield context.call_activity(
        "prepare_prompt_blob",
        {"batch_id": batch_id, "prompt_text": prompt_text},
    )

    # 2) Dispatch every (CV × run) to Service Bus, then await its event.
    dispatch_tasks = []
    event_tasks = []
    run_index_map: dict[str, tuple[str, int]] = {}  # run_id -> (application_id, run_index)
    for cv in cvs:
        for run_index in range(run_count):
            run_id = _mint_run_id(batch_id, cv["applicationId"], run_index)
            run_index_map[run_id] = (cv["applicationId"], run_index)
            dispatch_input = {
                "batch_id": batch_id,
                "job_id": payload.job_id,
                "run_id": run_id,
                "application_id": cv["applicationId"],
                "document_id": cv["documentId"],
                "file_name": cv["fileName"],
                "mime_type": cv["mimeType"],
                "blob_uri": cv["blobUri"],
                "sha256": cv["sha256"],
                "run_index": run_index,
                "prompt_blob_uri": prompt_blob_uri,
                "correlation_id": correlation_id,
                "traceparent": traceparent,
            }
            dispatch_tasks.append(context.call_activity("dispatch_run", dispatch_input))
            event_tasks.append(context.wait_for_external_event(f"run-{run_id}"))

    # Fire all dispatches in parallel (failures bubble up here).
    dispatched_runs = yield context.task_all(dispatch_tasks)
    dispatched_at = context.current_utc_datetime.isoformat()
    for dispatched_run in dispatched_runs:
        _record_dispatched_run(
            progress,
            run_id=dispatched_run["run_id"],
            updated_at=dispatched_at,
        )
        event_sequence += 1
        yield context.call_activity(
            "project_live_progress",
            build_live_progress_event(
                event_type="run.dispatched",
                progress=progress,
                occurred_at=dispatched_at,
                sequence=event_sequence,
                correlation_id=correlation_id,
                traceparent=traceparent,
                run_id=dispatched_run["run_id"],
            ),
        )
    context.set_custom_status(progress)

    # Now wait for every per-run result event raised by result_intake.
    pending_events = list(event_tasks)
    run_results = []
    while pending_events:
        completed_event = yield context.task_any(pending_events)
        pending_events = [task for task in pending_events if task != completed_event]
        run_result = _coerce_run_result_payload(completed_event.result)
        run_results.append(run_result)
        occurred_at = context.current_utc_datetime.isoformat()
        _record_run_result(
            progress,
            run_result=run_result,
            updated_at=occurred_at,
        )
        context.set_custom_status(progress)
        event_sequence += 1
        yield context.call_activity(
            "project_live_progress",
            _build_run_terminal_live_event(
                progress=progress,
                occurred_at=occurred_at,
                sequence=event_sequence,
                default_correlation_id=correlation_id,
                default_traceparent=traceparent,
                run_result=run_result,
            ),
        )
        application_id, _ = run_index_map[run_result["run_id"]]
        application = _find_application(progress, application_id)
        if (
            application is not None
            and _is_application_terminal(application)
            and application_id not in emitted_application_events
        ):
            emitted_application_events.add(application_id)
            event_sequence += 1
            yield context.call_activity(
                "project_live_progress",
                _build_application_terminal_live_event(
                    progress=progress,
                    occurred_at=occurred_at,
                    sequence=event_sequence,
                    correlation_id=str(run_result.get("correlation_id") or correlation_id),
                    traceparent=str(run_result.get("traceparent") or traceparent),
                    application_id=application_id,
                ),
            )

    # 3) Aggregate + persist.
    finalize_input = {
        "batch_id": batch_id,
        "cvs": [dict(cv) for cv in cvs],
        "run_results": [
            {**rr, "_application_id": run_index_map[rr["run_id"]][0],
             "_run_index": run_index_map[rr["run_id"]][1]}
            for rr in run_results
        ],
    }
    final_result = yield context.call_activity("finalize_batch", finalize_input)
    progress["status"] = "cancelled" if _is_cancelled_batch(progress) else "completed"
    progress["lastUpdatedAt"] = context.current_utc_datetime.isoformat()
    context.set_custom_status(progress)
    event_sequence += 1
    yield context.call_activity(
        "project_live_progress",
        _build_batch_terminal_live_event(
            progress=progress,
            occurred_at=context.current_utc_datetime.isoformat(),
            sequence=event_sequence,
            correlation_id=correlation_id,
            traceparent=traceparent,
        ),
    )
    return final_result


# ── Activity: stage the inline prompt to blob ────────────────────────────────
@bp.activity_trigger(input_name="payload")
def prepare_prompt_blob(payload):
    settings = get_settings()
    batch_id = payload["batch_id"]
    prompt_text: str = payload["prompt_text"] or ""

    container = settings.blob_results_container
    blob_path = f"batches/{batch_id}/prompt.txt"
    blob_uri = _upload_blob(
        account=settings.blob_account,
        container=container,
        path=blob_path,
        data=prompt_text.encode("utf-8"),
        content_type="text/plain; charset=utf-8",
    )
    return blob_uri


# ── Activity: dispatch one (CV × run) to Service Bus ─────────────────────────
@bp.activity_trigger(input_name="payload")
def dispatch_run(payload):
    settings = get_settings()
    inp = DispatchRunInput.model_validate(payload)
    dispatched_at = datetime.now(timezone.utc).isoformat()

    _verify_input_blob_sha256(blob_uri=inp.blob_uri, expected_sha256=inp.sha256)

    # 1) Persist the runId → batchId mapping so result_intake can route.
    #    Flat path (no batchId prefix) — result_intake doesn't know batchId yet.
    index_path = f"run-index/{inp.run_id}.json"
    _upload_blob(
        account=settings.blob_account,
        container=settings.blob_results_container,
        path=index_path,
        data=json.dumps(
            {
                "batchId": inp.batch_id,
                "jobId": inp.job_id,
                "runId": inp.run_id,
                "applicationId": inp.application_id,
                "documentId": inp.document_id,
                "runIndex": inp.run_index,
                "dispatchedAt": dispatched_at,
            }
        ).encode("utf-8"),
        content_type="application/json",
        overwrite=True,
    )

    # 2) Build and send the RunMessage to SB engine-runs.
    msg = RunMessage(
        message_id=str(uuid.uuid4()),
        run_id=inp.run_id,
        engine="awreason",
        parameters=RunParameters(
            cv_blob_uris=[inp.blob_uri],
            prompt_blob_uri=inp.prompt_blob_uri,
        ),
        correlation_id=inp.correlation_id or inp.batch_id,
        enqueued_at=dispatched_at,
    )
    app_props: dict[str, str] = {"correlationId": msg.correlation_id, "runId": inp.run_id}
    if inp.traceparent:
        app_props["traceparent"] = inp.traceparent
    _send_run_message(
        namespace=settings.sb_namespace,
        queue=settings.sb_runs_queue,
        msg_json=msg.model_dump_json(),
        message_id=msg.message_id,
        correlation_id=msg.correlation_id,
        application_properties=app_props,
    )
    return {"run_id": inp.run_id, "dispatched": True}


# ── Activity: finalize + persist batch result to blob ────────────────────────
@bp.activity_trigger(input_name="payload")
def finalize_batch(payload):
    settings = get_settings()
    inp = FinalizeBatchInput.model_validate(payload)

    by_app: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in inp.run_results:
        by_app[r["_application_id"]].append(r)

    cv_blocks: list[dict[str, Any]] = []
    for cv in inp.cvs:
        app_id = cv["applicationId"]
        runs = sorted(by_app.get(app_id, []), key=lambda x: x["_run_index"])
        first_error = next(
            (r.get("error_message") for r in runs if r.get("status") != "Succeeded" and r.get("error_message")),
            None,
        )
        run_payloads = [
            {
                "runId": r.get("run_id"),
                "runIndex": r["_run_index"],
                "documentId": cv["documentId"],
                "status": r.get("status"),
                "durationMs": r.get("duration_ms"),
                "tokensPrompt": r.get("tokens_prompt"),
                "tokensCompletion": r.get("tokens_completion"),
                "correlationId": r.get("correlation_id"),
                "traceparent": r.get("traceparent"),
                "artifacts": r.get("artifacts"),
                "errorMessage": r.get("error_message"),
            }
            for r in runs
        ]
        aggregated = _aggregate(run_payloads)
        cv_blocks.append({
            "applicationId": app_id,
            "documentId": cv["documentId"],
            "runs": run_payloads,
            "aggregated": aggregated,
            "error": ({"code": "RUN_FAILED", "message": first_error} if first_error else None),
        })

    result_doc = {"cvs": cv_blocks}

    # Persist the final document to blob so clients can pick it up later.
    blob_path = f"batches/{inp.batch_id}/result.json"
    _upload_blob(
        account=settings.blob_account,
        container=settings.blob_results_container,
        path=blob_path,
        data=json.dumps(result_doc).encode("utf-8"),
        content_type="application/json",
        overwrite=True,
    )
    return result_doc


@bp.activity_trigger(input_name="payload")
def project_live_progress(payload):
    return project_live_progress_event(payload)


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Aggregate per-CV scoring across runs.

    The engine emits one ``output.json`` artifact per run with shape::

        {
          "overall_score": float,           # or "score"
          "sub_scores": [...],              # or "scores"
          "must_haves": [{"met": bool}, ...],  # or "must_have_results"
          "variance": float                 # optional
        }

    For each succeeded run we fetch ``output.json`` from its ``artifacts[]``
    list, then aggregate: median of ``overall_score``, mode of derived
    decisions (``Approve`` if all must-haves met, else ``Reject``), and
    ``mustHaveResult`` = AND of all per-run must-have outcomes.
    """
    if not runs:
        return None
    succeeded = [r for r in runs if r.get("status") == "Succeeded"]
    if not succeeded:
        return None

    outputs: list[dict[str, Any]] = []
    source_artifacts: list[dict[str, Any]] = []
    for r in succeeded:
        out = _read_output_artifact(r.get("artifacts") or [])
        if out is not None:
            outputs.append(out)
        for artifact in r.get("artifacts") or []:
            if isinstance(artifact, dict):
                source_artifacts.append(
                    {
                        "name": artifact.get("name"),
                        "blob_uri": artifact.get("blob_uri"),
                        "sha256": artifact.get("sha256"),
                    }
                )

    return aggregate_run_outputs(
        outputs,
        profile=AGGREGATION_PROFILE_CV,
        method="median",
        source_artifacts=source_artifacts,
    )


def _read_output_artifact(artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Download and parse the engine output artifact for a run.

    Prefers ``output.json`` for strict contract alignment and falls back to the
    first JSON artifact with a blob URI for compatibility.
    """
    item = next(
        (
            a
            for a in artifacts
            if isinstance(a, dict)
            and a.get("name") == "output.json"
            and a.get("blob_uri")
        ),
        None,
    )
    if item is None:
        item = next(
            (
                a
                for a in artifacts
                if isinstance(a, dict)
                and isinstance(a.get("name"), str)
                and a["name"].lower().endswith(".json")
                and a.get("blob_uri")
            ),
            None,
        )
    if item is None or not item.get("blob_uri"):
        return None
    try:
        from azure.identity import DefaultAzureCredential

        client = BlobClient.from_blob_url(item["blob_uri"], credential=DefaultAzureCredential())
        data = client.download_blob().readall()
        text = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data)
        # Some engine payloads append explanatory prose after a valid JSON object.
        # Parse only the first JSON value so aggregation still works.
        decoder = json.JSONDecoder()
        parsed, _ = decoder.raw_decode(text.lstrip())
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001 — best-effort aggregation
        logger.exception("failed to read output artifact at %s", item.get("blob_uri"))
        return None
def _verify_input_blob_sha256(*, blob_uri: str, expected_sha256: str) -> None:
    if not expected_sha256:
        return

    try:
        from azure.identity import DefaultAzureCredential

        client = BlobClient.from_blob_url(blob_uri, credential=DefaultAzureCredential())
        downloader = client.download_blob()
        digest = hashlib.sha256()
        for chunk in downloader.chunks():
            digest.update(chunk)
        actual_sha256 = digest.hexdigest()
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to verify input blob sha256 at %s", blob_uri)
        raise RuntimeError(f"failed to verify input blob sha256 for {blob_uri}") from exc

    if actual_sha256.lower() != expected_sha256.lower():
        raise ValueError(f"sha256 mismatch for {blob_uri}")


# ── Helpers: blob + service bus (sync clients run in activity threads) ───────
def _blob_service_client(account: str) -> BlobServiceClient:
    from azure.identity import DefaultAzureCredential

    url = (
        account if account.startswith("https://")
        else f"https://{account}.blob.core.windows.net"
    )
    return BlobServiceClient(account_url=url, credential=DefaultAzureCredential())


def _upload_blob(
    *,
    account: str,
    container: str,
    path: str,
    data: bytes,
    content_type: str,
    overwrite: bool = True,
) -> str:
    client = _blob_service_client(account).get_blob_client(container=container, blob=path)
    from azure.storage.blob import ContentSettings

    client.upload_blob(
        data,
        overwrite=overwrite,
        content_settings=ContentSettings(content_type=content_type),
    )
    return client.url


def _send_run_message(
    *,
    namespace: str,
    queue: str,
    msg_json: str,
    message_id: str,
    correlation_id: str,
    application_properties: dict[str, str] | None = None,
) -> None:
    from azure.identity import DefaultAzureCredential

    fqns = namespace if namespace.endswith(".servicebus.windows.net") else f"{namespace}.servicebus.windows.net"
    credential = DefaultAzureCredential()
    with ServiceBusClient(fully_qualified_namespace=fqns, credential=credential) as sb:
        with sb.get_queue_sender(queue) as sender:
            msg = ServiceBusMessage(msg_json, content_type="application/json")
            msg.message_id = message_id
            msg.correlation_id = correlation_id
            if application_properties:
                msg.application_properties = application_properties  # type: ignore[assignment]
            sender.send_messages(msg)


# ── Internal HTTP routes (FastAPI → Functions host) ──────────────────────────
@bp.route(route="orchestration/start", methods=["POST"])
@bp.durable_client_input(client_name="client")
async def http_start(req, client):
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(status_code=400, body="invalid json")

    instance_id = body.get("instance_id")
    payload = body.get("payload")
    if not instance_id or payload is None:
        return func.HttpResponse(status_code=400, body="instance_id and payload required")

    # Propagate correlation + W3C traceparent into the orchestrator input.
    correlation_id = req.headers.get("x-correlation-id", "")
    traceparent = req.headers.get("traceparent", "")
    if isinstance(payload, dict):
        merged: dict[str, Any] = {**payload}
        if correlation_id:
            merged["correlationId"] = correlation_id
        if traceparent:
            merged["traceparent"] = traceparent
        payload = merged

    existing = await client.get_status(instance_id)
    if _status_exists(existing):
        return func.HttpResponse(
            status_code=200,
            body=json.dumps({"instance_id": instance_id}),
            mimetype="application/json",
        )

    await client.start_new(_ORCHESTRATOR_NAME, instance_id=instance_id, client_input=payload)
    return func.HttpResponse(
        status_code=202,
        body=json.dumps({"instance_id": instance_id}),
        mimetype="application/json",
    )


@bp.route(route="orchestration/{instance_id}", methods=["GET"])
@bp.durable_client_input(client_name="client")
async def http_status(req, client):
    instance_id = req.route_params.get("instance_id", "")
    status_obj = await client.get_status(instance_id, show_input=False)
    if not _status_exists(status_obj):
        # Durable history may have been purged. Tell FastAPI to fall back to blob.
        return func.HttpResponse(status_code=404)

    body = _normalize_status(status_obj)
    return func.HttpResponse(
        status_code=200, body=json.dumps(body), mimetype="application/json"
    )


@bp.route(route="orchestration/{instance_id}/terminate", methods=["POST"])
@bp.durable_client_input(client_name="client")
async def http_terminate(req, client):
    instance_id = req.route_params.get("instance_id", "")
    status_obj = await client.get_status(instance_id)
    if not _status_exists(status_obj):
        return func.HttpResponse(status_code=404)

    headers = getattr(req, "headers", {}) or {}
    correlation_id = headers.get("x-correlation-id", "")
    traceparent = headers.get("traceparent", "")
    occurred_at = datetime.now(timezone.utc).isoformat()

    if status_obj.runtime_status == df.OrchestrationRuntimeStatus.Completed:
        return func.HttpResponse(
            status_code=409,
            body=json.dumps({"status": "completed"}),
            mimetype="application/json",
        )
    if status_obj.runtime_status == df.OrchestrationRuntimeStatus.Terminated:
        project_live_progress_event(
            _build_batch_state_live_event(
                instance_id=instance_id,
                status_obj=status_obj,
                status="cancelled",
                event_type="batch.cancelled",
                occurred_at=occurred_at,
                correlation_id=correlation_id,
                traceparent=traceparent,
            )
        )
        return func.HttpResponse(
            status_code=200,
            body=json.dumps({"status": "cancelled"}),
            mimetype="application/json",
        )

    reason = "client cancelled"
    try:
        body = req.get_json()
        reason = body.get("reason", reason)
    except ValueError:
        pass
    await client.terminate(instance_id, reason)
    project_live_progress_event(
        _build_batch_state_live_event(
            instance_id=instance_id,
            status_obj=status_obj,
            status="cancelling",
            event_type="batch.cancelling",
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            traceparent=traceparent,
        )
    )
    return func.HttpResponse(
        status_code=202,
        body=json.dumps({"status": "cancelling"}),
        mimetype="application/json",
    )


def _normalize_status(s: Any) -> dict[str, Any]:
    """Map Durable runtime status → platform-contract status JSON."""
    mapping = {
        df.OrchestrationRuntimeStatus.Pending: "queued",
        df.OrchestrationRuntimeStatus.Running: "running",
        df.OrchestrationRuntimeStatus.Completed: "completed",
        df.OrchestrationRuntimeStatus.Failed: "failed",
        df.OrchestrationRuntimeStatus.Terminated: "cancelled",
        df.OrchestrationRuntimeStatus.Canceled: "cancelled",
    }
    status_str = mapping.get(s.runtime_status, "running")
    progress = s.custom_status if isinstance(s.custom_status, dict) else None
    result = None
    error = None
    if status_str == "completed" and s.output is not None:
        result = s.output if isinstance(s.output, dict) else json.loads(s.output)
    if status_str == "failed":
        error = {
            "code": "ORCHESTRATION_FAILED",
            "message": (s.output or "orchestration failed")
            if isinstance(s.output, str)
            else "orchestration failed",
        }
    return {
        "status": status_str,
        "progress": progress,
        "result": result,
        "error": error,
        "retryAfterSeconds": 10 if status_str in ("queued", "running") else None,
    }


def _status_exists(status_obj: Any) -> bool:
    """Return True only when Durable returned a materialized orchestration instance.

    Some Durable SDK/runtime combinations can return a placeholder status object
    for unknown instance IDs. Those placeholders typically have no timestamps,
    no function name, and no custom status.
    """
    if status_obj is None:
        return False

    runtime_status = getattr(status_obj, "runtime_status", None)
    created_time = getattr(status_obj, "created_time", None)
    last_updated_time = getattr(status_obj, "last_updated_time", None)
    name = getattr(status_obj, "name", None)
    custom_status = getattr(status_obj, "custom_status", None)
    output = getattr(status_obj, "output", None)

    if runtime_status is None and created_time is None and last_updated_time is None:
        return False
    if created_time is None and last_updated_time is None and not name:
        return bool(custom_status or output)
    return True
