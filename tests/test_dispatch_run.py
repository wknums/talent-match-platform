"""Tests for the ``dispatch_run`` activity (SB send + run-index write).

Validates:
- ``RunMessage`` payload shape matches engine contract.
- W3C ``traceparent`` is stamped onto SB application_properties.
- The run-index blob is written before the SB send.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import orchestrator.functions.fanout as fanout
from orchestrator.sb_contracts import RunMessage


@pytest.fixture()
def settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SB_NAMESPACE", "sb-test")
    monkeypatch.setenv("SB_RUNS_QUEUE", "engine-runs")
    monkeypatch.setenv("BLOB_ACCOUNT", "acct")
    monkeypatch.setenv("BLOB_RESULTS_CONTAINER", "batch-results")
    from runtime.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]


def _payload(**overrides):
    base = {
        "batch_id": "b1",
        "job_id": "job-1",
        "run_id": "r1",
        "application_id": "app-1",
        "document_id": "doc-1",
        "file_name": "cv.pdf",
        "mime_type": "application/pdf",
        "blob_uri": "https://acct.blob.core.windows.net/cv/cv.pdf",
        "sha256": "a" * 64,
        "run_index": 0,
        "prompt_blob_uri": "https://acct.blob.core.windows.net/batch-results/batches/b1/prompt.txt",
        "correlation_id": "cid-1",
        "traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01",
    }
    base.update(overrides)
    return base


def test_dispatch_run_writes_run_index_and_sends_run_message(settings) -> None:
    sent: dict = {}

    def fake_upload(*, account, container, path, data, content_type, overwrite=True):
        sent.setdefault("uploads", []).append((path, data, content_type))
        return f"https://{account}.blob.core.windows.net/{container}/{path}"

    def fake_send(*, namespace, queue, msg_json, message_id, correlation_id, application_properties=None):
        sent["sb"] = {
            "namespace": namespace,
            "queue": queue,
            "msg_json": msg_json,
            "message_id": message_id,
            "correlation_id": correlation_id,
            "application_properties": application_properties,
        }

    with patch.object(fanout, "_verify_input_blob_sha256", return_value=None), \
         patch.object(fanout, "_upload_blob", side_effect=fake_upload), \
         patch.object(fanout, "_send_run_message", side_effect=fake_send):
        out = fanout.dispatch_run(_payload())

    assert out == {"run_id": "r1", "dispatched": True}
    # run-index blob written, flat path.
    paths = [u[0] for u in sent["uploads"]]
    assert "run-index/r1.json" in paths
    idx_data = next(u[1] for u in sent["uploads"] if u[0] == "run-index/r1.json")
    idx = json.loads(idx_data)
    assert idx["batchId"] == "b1"
    assert idx["jobId"] == "job-1"
    assert idx["runId"] == "r1"
    assert idx["applicationId"] == "app-1"
    assert idx["documentId"] == "doc-1"
    assert idx["runIndex"] == 0
    assert "dispatchedAt" in idx

    # SB send happened with the right shape.
    sb = sent["sb"]
    assert sb["queue"] == "engine-runs"
    msg = RunMessage.model_validate_json(sb["msg_json"])
    assert msg.run_id == "r1"
    assert msg.engine == "awreason"
    assert msg.parameters.cv_blob_uris == ["https://acct.blob.core.windows.net/cv/cv.pdf"]
    assert msg.parameters.prompt_blob_uri.endswith("/prompt.txt")
    assert msg.correlation_id == "cid-1"
    # Application properties carry W3C traceparent and runId.
    assert sb["application_properties"]["traceparent"].startswith("00-")
    assert sb["application_properties"]["runId"] == "r1"
    assert sb["application_properties"]["correlationId"] == "cid-1"


def test_dispatch_run_omits_traceparent_when_absent(settings) -> None:
    captured: dict = {}

    def fake_send(*, application_properties=None, **_):
        captured["app_props"] = application_properties

    with patch.object(fanout, "_verify_input_blob_sha256", return_value=None), \
         patch.object(fanout, "_upload_blob", return_value="x"), \
         patch.object(fanout, "_send_run_message", side_effect=fake_send):
        fanout.dispatch_run(_payload(traceparent=""))

    assert "traceparent" not in captured["app_props"]
    assert "correlationId" in captured["app_props"]


def test_verify_input_blob_sha256_accepts_matching_content() -> None:
    downloader = MagicMock()
    downloader.chunks.return_value = [b"hello ", b"world"]

    with patch("orchestrator.functions.fanout.BlobClient") as blob_client:
        blob_client.from_blob_url.return_value.download_blob.return_value = downloader
        fanout._verify_input_blob_sha256(
            blob_uri="https://acct.blob.core.windows.net/cv/cv.pdf",
            expected_sha256="b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
        )


def test_dispatch_run_rejects_sha256_mismatch_before_side_effects(settings) -> None:
    with patch.object(fanout, "_verify_input_blob_sha256", side_effect=ValueError("sha256 mismatch")), \
         patch.object(fanout, "_upload_blob") as upload_blob, \
         patch.object(fanout, "_send_run_message") as send_run_message:
        with pytest.raises(ValueError, match="sha256 mismatch"):
            fanout.dispatch_run(_payload())

    upload_blob.assert_not_called()
    send_run_message.assert_not_called()
