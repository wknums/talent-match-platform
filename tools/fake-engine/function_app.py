"""Fake engine — drop-in replacement for awr-engine over Service Bus.

Consumes ``RunMessage`` from ``engine-runs``, optionally sleeps / fails /
returns transient, writes a synthetic ``output.json`` artifact to blob, then
publishes ``RunResultMessage`` to ``engine-results``. Zero LLM tokens spent.

Knobs (env vars):
    SB_NAMESPACE                 fully-qualified Service Bus namespace
    SB_RUNS_QUEUE                default: engine-runs
    SB_RESULTS_QUEUE             default: engine-results
    BLOB_ACCOUNT                 storage account name for fake artifacts
    FAKE_ARTIFACT_CONTAINER      default: batch-results
    FAKE_LATENCY_MS_MIN          default: 50
    FAKE_LATENCY_MS_MAX          default: 250
    FAKE_FAILURE_RATE            0.0–1.0, returns status="Failed"  default: 0
    FAKE_TRANSIENT_RATE          0.0–1.0, raises (SB redelivery)   default: 0
    FAKE_SCORE_MIN               default: 5.5
    FAKE_SCORE_MAX               default: 9.5
    FAKE_MUST_HAVE_PASS_RATE     0.0–1.0  default: 0.85
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid
from datetime import datetime, timezone

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.storage.blob import BlobClient

logger = logging.getLogger(__name__)
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

_credential = DefaultAzureCredential()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _coerce_str(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    return str(v)


def _build_output(run_id: str) -> dict:
    score_min = _env_float("FAKE_SCORE_MIN", 5.5)
    score_max = _env_float("FAKE_SCORE_MAX", 9.5)
    pass_rate = _env_float("FAKE_MUST_HAVE_PASS_RATE", 0.85)
    score = round(random.uniform(score_min, score_max), 2)
    return {
        "run_id": run_id,
        "overall_score": score,
        "sub_scores": {
            "experience": round(random.uniform(score_min, score_max), 2),
            "skills": round(random.uniform(score_min, score_max), 2),
            "education": round(random.uniform(score_min, score_max), 2),
        },
        "must_haves": [
            {"name": "minimum_experience", "met": random.random() < pass_rate},
            {"name": "required_skills", "met": random.random() < pass_rate},
        ],
        "variance": 0.0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_output_artifact(account: str, container: str, run_id: str, body: dict) -> str:
    path = f"engine-outputs/{run_id}/output.json"
    url = f"https://{account}.blob.core.windows.net/{container}/{path}"
    bc = BlobClient.from_blob_url(url, credential=_credential)
    data = json.dumps(body).encode("utf-8")
    bc.upload_blob(data, overwrite=True, content_type="application/json")
    return url


def _send_result(
    namespace: str,
    queue: str,
    body: dict,
    correlation_id: str,
    application_properties: dict[str, str],
) -> None:
    with ServiceBusClient(namespace, _credential) as sb:
        sender = sb.get_queue_sender(queue_name=queue)
        with sender:
            msg = ServiceBusMessage(
                body=json.dumps(body),
                content_type="application/json",
                correlation_id=correlation_id,
                message_id=str(uuid.uuid4()),
            )
            msg.application_properties = application_properties  # type: ignore[assignment]
            sender.send_messages(msg)


@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name=os.environ.get("SB_RUNS_QUEUE", "engine-runs"),
    connection="SbConnection",
)
def fake_engine_run(msg: func.ServiceBusMessage) -> None:
    start = time.monotonic()
    body = msg.get_body().decode("utf-8")
    inbound = json.loads(body)
    run_id = inbound.get("run_id") or str(uuid.uuid4())
    correlation_id = inbound.get("correlation_id") or ""

    app_props = getattr(msg, "application_properties", None) or {}
    traceparent = _coerce_str(app_props.get("traceparent") or app_props.get(b"traceparent"))

    # Knob 1: transient error → raise to force SB redelivery.
    if random.random() < _env_float("FAKE_TRANSIENT_RATE", 0.0):
        logger.warning("fake-engine transient for run_id=%s", run_id)
        raise RuntimeError("fake-engine transient")

    # Knob 2: artificial latency.
    lo = _env_float("FAKE_LATENCY_MS_MIN", 50)
    hi = max(lo, _env_float("FAKE_LATENCY_MS_MAX", 250))
    time.sleep(random.uniform(lo, hi) / 1000.0)

    # Knob 3: failure → emit Failed result without artifact.
    fail = random.random() < _env_float("FAKE_FAILURE_RATE", 0.0)

    namespace = os.environ["SB_NAMESPACE"]
    results_queue = os.environ.get("SB_RESULTS_QUEUE", "engine-results")
    blob_account = os.environ["BLOB_ACCOUNT"]
    container = os.environ.get("FAKE_ARTIFACT_CONTAINER", "batch-results")

    artifacts: list[dict] | None = None
    if not fail:
        out = _build_output(run_id)
        url = _write_output_artifact(blob_account, container, run_id, out)
        artifacts = [{
            "name": "output.json",
            "blob_uri": url,
            "mime": "application/json",
            "size_bytes": None,
            "sha256": None,
        }]

    duration_ms = int((time.monotonic() - start) * 1000)
    result_body = {
        "run_id": run_id,
        "status": "Failed" if fail else "Succeeded",
        "duration_ms": duration_ms,
        "tokens_prompt": 0,
        "tokens_completion": 0,
        "error_message": "fake-engine synthetic failure" if fail else None,
        "correlation_id": correlation_id,
        "artifacts": artifacts,
    }

    out_props: dict[str, str] = {"correlationId": correlation_id, "runId": run_id}
    if traceparent:
        out_props["traceparent"] = traceparent
    _send_result(namespace, results_queue, result_body, correlation_id, out_props)
    logger.info("fake-engine done run_id=%s status=%s ms=%d", run_id, result_body["status"], duration_ms)
