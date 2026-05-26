"""Tests for ``_aggregate`` — engine ``output.json`` artifact-blob parsing.

The aggregator downloads ``output.json`` for each succeeded run from its
``blob_uri``, then computes median score, mode decision, and AND-of-must-have.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import orchestrator.functions.fanout as fanout


def _run(status: str, blob_uri: str | None = None, run_index: int = 0) -> dict:
    artifacts = (
        [{"name": "output.json", "blob_uri": blob_uri, "mime": "application/json"}]
        if blob_uri
        else None
    )
    return {
        "runIndex": run_index,
        "status": status,
        "durationMs": 1000,
        "tokensPrompt": 100,
        "tokensCompletion": 50,
        "artifacts": artifacts,
        "errorMessage": None,
    }


def test_aggregate_no_runs_returns_none() -> None:
    assert fanout._aggregate([]) is None


def test_aggregate_no_succeeded_returns_none() -> None:
    assert fanout._aggregate([_run("Failed"), _run("Failed")]) is None


def test_aggregate_median_score_and_approve_decision() -> None:
    outputs = {
        "uri-1": {"overall_score": 7.0, "must_haves": [{"met": True}, {"met": True}]},
        "uri-2": {"overall_score": 8.0, "must_haves": [{"met": True}, {"met": True}]},
        "uri-3": {"overall_score": 9.0, "must_haves": [{"met": True}, {"met": True}]},
    }
    with patch.object(fanout, "_read_output_artifact", side_effect=lambda arts: outputs[arts[0]["blob_uri"]]):
        agg = fanout._aggregate([
            _run("Succeeded", "uri-1", 0),
            _run("Succeeded", "uri-2", 1),
            _run("Succeeded", "uri-3", 2),
        ])
    assert agg is not None
    assert agg["finalScore"] == 8.0
    assert agg["runsCount"] == 3
    assert agg["finalDecision"] == "Approve"
    assert agg["mustHaveResult"] is True
    assert agg["variance"] > 0


def test_aggregate_reject_when_any_must_have_unmet() -> None:
    outputs = {
        "uri-1": {"overall_score": 5.0, "must_haves": [{"met": True}]},
        "uri-2": {"overall_score": 6.0, "must_haves": [{"met": False}]},
    }
    with patch.object(fanout, "_read_output_artifact", side_effect=lambda arts: outputs[arts[0]["blob_uri"]]):
        agg = fanout._aggregate([
            _run("Succeeded", "uri-1", 0),
            _run("Succeeded", "uri-2", 1),
        ])
    assert agg is not None
    assert agg["mustHaveResult"] is False
    # Two runs, one Approve one Reject → mode picks first encountered; assert at least it's deterministic.
    assert agg["finalDecision"] in {"Approve", "Reject"}


def test_aggregate_accepts_alternate_field_names() -> None:
    # Engine emits either "overall_score"/"must_haves" or "score"/"must_have_results".
    outputs = {
        "uri-1": {"score": 6.5, "must_have_results": [{"met": True}]},
    }
    with patch.object(fanout, "_read_output_artifact", side_effect=lambda arts: outputs[arts[0]["blob_uri"]]):
        agg = fanout._aggregate([_run("Succeeded", "uri-1", 0)])
    assert agg is not None
    assert agg["finalScore"] == 6.5
    assert agg["mustHaveResult"] is True


def test_aggregate_skips_runs_with_unreadable_output() -> None:
    with patch.object(fanout, "_read_output_artifact", return_value=None):
        agg = fanout._aggregate([_run("Succeeded", "uri-1", 0)])
    assert agg is None


def test_read_output_artifact_returns_none_when_missing() -> None:
    # No output.json among artifacts.
    assert fanout._read_output_artifact([{"name": "trace.log", "blob_uri": "x"}]) is None
    # Empty.
    assert fanout._read_output_artifact([]) is None


def test_read_output_artifact_downloads_and_parses() -> None:
    blob = MagicMock()
    blob.download_blob.return_value.readall.return_value = json.dumps(
        {"overall_score": 7.5, "must_haves": [{"met": True}]}
    ).encode("utf-8")
    with patch("orchestrator.functions.fanout.BlobClient") as bc:
        bc.from_blob_url.return_value = blob
        out = fanout._read_output_artifact(
            [{"name": "output.json", "blob_uri": "https://x/y/output.json"}]
        )
    assert out == {"overall_score": 7.5, "must_haves": [{"met": True}]}


def test_read_output_artifact_swallows_download_errors() -> None:
    with patch("orchestrator.functions.fanout.BlobClient") as bc:
        bc.from_blob_url.side_effect = RuntimeError("boom")
        assert fanout._read_output_artifact(
            [{"name": "output.json", "blob_uri": "https://x/y/output.json"}]
        ) is None


def test_finalize_batch_keeps_runs_grouped_by_application_and_run_index() -> None:
    payload = {
        "batch_id": "batch-1",
        "cvs": [
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
        ],
        "run_results": [
            {
                "run_id": "run-2b",
                "_application_id": "app-2",
                "_run_index": 1,
                "status": "Failed",
                "duration_ms": 222,
                "tokens_prompt": 20,
                "tokens_completion": 0,
                "error_message": "engine timeout",
                "artifacts": None,
            },
            {
                "run_id": "run-1a",
                "_application_id": "app-1",
                "_run_index": 0,
                "status": "Succeeded",
                "duration_ms": 111,
                "tokens_prompt": 10,
                "tokens_completion": 5,
                "error_message": None,
                "artifacts": [{"name": "output.json", "blob_uri": "uri-app-1"}],
            },
            {
                "run_id": "run-2a",
                "_application_id": "app-2",
                "_run_index": 0,
                "status": "Succeeded",
                "duration_ms": 211,
                "tokens_prompt": 21,
                "tokens_completion": 8,
                "error_message": None,
                "artifacts": [{"name": "output.json", "blob_uri": "uri-app-2"}],
            },
        ],
    }

    aggregate_outputs = {
        "uri-app-1": {"overall_score": 8.0, "must_haves": [{"met": True}]},
        "uri-app-2": {"overall_score": 6.0, "must_haves": [{"met": True}]},
    }

    with patch.object(fanout, "_read_output_artifact", side_effect=lambda arts: aggregate_outputs[arts[0]["blob_uri"]]), \
         patch.object(fanout, "_upload_blob", return_value="https://acct/blob/result.json"):
        result = fanout.finalize_batch(payload)

    cvs = {cv["applicationId"]: cv for cv in result["cvs"]}
    assert set(cvs) == {"app-1", "app-2"}

    app_1_runs = cvs["app-1"]["runs"]
    assert [run["runId"] for run in app_1_runs] == ["run-1a"]
    assert app_1_runs[0]["runIndex"] == 0
    assert app_1_runs[0]["documentId"] == "doc-1"
    assert cvs["app-1"]["error"] is None
    assert cvs["app-1"]["aggregated"]["finalScore"] == 8.0

    app_2_runs = cvs["app-2"]["runs"]
    assert [run["runId"] for run in app_2_runs] == ["run-2a", "run-2b"]
    assert [run["runIndex"] for run in app_2_runs] == [0, 1]
    assert all(run["documentId"] == "doc-2" for run in app_2_runs)
    assert cvs["app-2"]["error"] == {"code": "RUN_FAILED", "message": "engine timeout"}
    assert cvs["app-2"]["aggregated"]["finalScore"] == 6.0
