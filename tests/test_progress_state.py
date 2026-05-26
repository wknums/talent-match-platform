"""Tests for Durable progress-state and lineage helpers in the fanout orchestrator.

These tests lock down the stronger in-flight progress model required by spec 002:
- submission-level counters advance as runs dispatch and complete,
- application-level lineage can be recovered without scanning unrelated runs,
- result metadata is attached back to the originating run.
"""

from __future__ import annotations

import orchestrator.functions.fanout as fanout


def _sample_cvs() -> list[dict[str, str]]:
    return [
        {
            "applicationId": "app-1",
            "documentId": "doc-1",
            "fileName": "cv-1.pdf",
            "mimeType": "application/pdf",
            "blobUri": "https://acct.blob.core.windows.net/cv/cv-1.pdf",
            "sha256": "a" * 64,
        },
        {
            "applicationId": "app-2",
            "documentId": "doc-2",
            "fileName": "cv-2.pdf",
            "mimeType": "application/pdf",
            "blobUri": "https://acct.blob.core.windows.net/cv/cv-2.pdf",
            "sha256": "b" * 64,
        },
    ]


def test_build_initial_progress_creates_submission_and_application_lineage() -> None:
    cvs = _sample_cvs()

    progress = fanout._build_initial_progress(  # type: ignore[attr-defined]
        batch_id="batch-1",
        job_id="job-1",
        cvs=cvs,
        run_count=2,
        updated_at="2026-05-22T10:00:00+00:00",
    )

    assert progress["submissionId"] == "batch-1"
    assert progress["batchId"] == "batch-1"
    assert progress["jobId"] == "job-1"
    assert progress["status"] == "queued"
    assert progress["cvsCompleted"] == 0
    assert progress["cvsTotal"] == 2
    assert progress["runsCompleted"] == 0
    assert progress["runsDispatched"] == 0
    assert progress["runsTotal"] == 4
    assert progress["lastUpdatedAt"] == "2026-05-22T10:00:00+00:00"

    apps = {app["applicationId"]: app for app in progress["applications"]}
    assert set(apps) == {"app-1", "app-2"}
    assert apps["app-1"]["documentId"] == "doc-1"
    assert apps["app-1"]["status"] == "queued"
    assert apps["app-1"]["runsCompleted"] == 0
    assert apps["app-1"]["runsTotal"] == 2
    assert len(apps["app-1"]["runs"]) == 2
    assert apps["app-1"]["runs"][0]["runIndex"] == 0
    assert apps["app-1"]["runs"][0]["status"] == "queued"


def test_record_dispatch_updates_submission_and_run_state() -> None:
    progress = fanout._build_initial_progress(  # type: ignore[attr-defined]
        batch_id="batch-1",
        job_id="job-1",
        cvs=_sample_cvs(),
        run_count=1,
        updated_at="2026-05-22T10:00:00+00:00",
    )
    run_id = progress["applications"][0]["runs"][0]["runId"]

    fanout._record_dispatched_run(  # type: ignore[attr-defined]
        progress,
        run_id=run_id,
        updated_at="2026-05-22T10:01:00+00:00",
    )

    app = progress["applications"][0]
    run = app["runs"][0]
    assert progress["status"] == "running"
    assert progress["runsDispatched"] == 1
    assert progress["runsCompleted"] == 0
    assert progress["lastUpdatedAt"] == "2026-05-22T10:01:00+00:00"
    assert app["status"] == "running"
    assert run["status"] == "dispatched"
    assert run["dispatchedAt"] == "2026-05-22T10:01:00+00:00"


def test_record_run_result_updates_counters_artifacts_and_application_completion() -> None:
    progress = fanout._build_initial_progress(  # type: ignore[attr-defined]
        batch_id="batch-1",
        job_id="job-1",
        cvs=_sample_cvs()[:1],
        run_count=2,
        updated_at="2026-05-22T10:00:00+00:00",
    )
    runs = progress["applications"][0]["runs"]
    for idx, run in enumerate(runs, start=1):
        fanout._record_dispatched_run(  # type: ignore[attr-defined]
            progress,
            run_id=run["runId"],
            updated_at=f"2026-05-22T10:0{idx}:00+00:00",
        )

    fanout._record_run_result(  # type: ignore[attr-defined]
        progress,
        run_result={
            "run_id": runs[0]["runId"],
            "status": "Succeeded",
            "duration_ms": 1200,
            "tokens_prompt": 100,
            "tokens_completion": 25,
            "artifacts": [{"name": "output.json", "blob_uri": "https://acct/blob/output.json"}],
            "error_message": None,
        },
        updated_at="2026-05-22T10:03:00+00:00",
    )

    assert progress["runsCompleted"] == 1
    assert progress["cvsCompleted"] == 0
    first_run = progress["applications"][0]["runs"][0]
    assert first_run["status"] == "Succeeded"
    assert first_run["artifactCount"] == 1
    assert first_run["artifactNames"] == ["output.json"]
    assert first_run["completedAt"] == "2026-05-22T10:03:00+00:00"

    fanout._record_run_result(  # type: ignore[attr-defined]
        progress,
        run_result={
            "run_id": runs[1]["runId"],
            "status": "Failed",
            "duration_ms": 1400,
            "tokens_prompt": 100,
            "tokens_completion": 0,
            "artifacts": None,
            "error_message": "engine timeout",
        },
        updated_at="2026-05-22T10:04:00+00:00",
    )

    assert progress["runsCompleted"] == 2
    assert progress["cvsCompleted"] == 1
    assert progress["status"] == "running"
    app = progress["applications"][0]
    assert app["status"] == "partial"
    assert app["runsCompleted"] == 2
    assert app["lastUpdatedAt"] == "2026-05-22T10:04:00+00:00"
    assert app["runs"][1]["errorMessage"] == "engine timeout"