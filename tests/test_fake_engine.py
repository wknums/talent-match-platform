"""Unit tests for the fake-engine SB handler.

Verifies the contract the platform expects:
- Reads ``traceparent`` from SB ``application_properties`` and echoes it back.
- Writes an ``output.json`` artifact whose blob_uri is returned in
  ``RunResultMessage.artifacts`` (so ``_aggregate`` can parse it).
- Honors ``FAKE_FAILURE_RATE``/``FAKE_TRANSIENT_RATE`` knobs.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make tools/fake-engine importable as a script-style Functions app.
_FAKE_DIR = Path(__file__).resolve().parents[1] / "tools" / "fake-engine"
if str(_FAKE_DIR) not in sys.path:
    sys.path.insert(0, str(_FAKE_DIR))


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SB_NAMESPACE", "sb-test.servicebus.windows.net")
    monkeypatch.setenv("SB_RESULTS_QUEUE", "engine-results")
    monkeypatch.setenv("BLOB_ACCOUNT", "acct")
    monkeypatch.setenv("FAKE_ARTIFACT_CONTAINER", "batch-results")
    monkeypatch.setenv("FAKE_LATENCY_MS_MIN", "0")
    monkeypatch.setenv("FAKE_LATENCY_MS_MAX", "0")
    monkeypatch.setenv("FAKE_FAILURE_RATE", "0")
    monkeypatch.setenv("FAKE_TRANSIENT_RATE", "0")
    # Reload module to re-read env-derived defaults if any.
    if "function_app" in sys.modules:
        del sys.modules["function_app"]
    mod = importlib.import_module("function_app")
    return mod


def _make_msg(run_id: str = "r1", traceparent: str | None = None) -> MagicMock:
    body = {
        "message_id": "m1",
        "run_id": run_id,
        "engine": "awreason",
        "parameters": {"cv_blob_uris": ["https://x/y.pdf"]},
        "correlation_id": "cid-1",
        "enqueued_at": "2026-05-19T00:00:00Z",
    }
    msg = MagicMock()
    msg.get_body.return_value = json.dumps(body).encode("utf-8")
    msg.application_properties = {"traceparent": traceparent} if traceparent else {}
    return msg


def _underlying(fn):
    """Unwrap the Azure Functions FunctionBuilder to the raw Python callable."""
    return fn._function._func if hasattr(fn, "_function") else fn


def test_fake_engine_succeeded_writes_artifact_and_emits_result(fake) -> None:
    msg = _make_msg(traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01")
    with patch.object(fake, "_write_output_artifact", return_value="https://acct/c/engine-outputs/r1/output.json") as wa, \
         patch.object(fake, "_send_result") as sr:
        _underlying(fake.fake_engine_run)(msg)

    wa.assert_called_once()
    sr.assert_called_once()
    args, kwargs = sr.call_args
    # _send_result(namespace, queue, body, correlation_id, application_properties)
    body = args[2]
    props = args[4]
    assert body["status"] == "Succeeded"
    assert body["run_id"] == "r1"
    assert body["correlation_id"] == "cid-1"
    assert body["artifacts"][0]["name"] == "output.json"
    assert body["artifacts"][0]["blob_uri"].endswith("/output.json")
    assert props["runId"] == "r1"
    assert props["correlationId"] == "cid-1"
    assert props["traceparent"].startswith("00-")


def test_fake_engine_failure_skips_artifact(fake, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_FAILURE_RATE", "1.0")
    msg = _make_msg()
    with patch.object(fake, "_write_output_artifact") as wa, \
         patch.object(fake, "_send_result") as sr:
        _underlying(fake.fake_engine_run)(msg)
    wa.assert_not_called()
    body = sr.call_args[0][2]
    assert body["status"] == "Failed"
    assert body["artifacts"] is None
    assert body["error_message"]


def test_fake_engine_transient_raises(fake, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_TRANSIENT_RATE", "1.0")
    msg = _make_msg()
    with patch.object(fake, "_write_output_artifact"), patch.object(fake, "_send_result"):
        with pytest.raises(RuntimeError):
            _underlying(fake.fake_engine_run)(msg)


def test_fake_engine_no_traceparent_omits_property(fake) -> None:
    msg = _make_msg()  # no traceparent
    with patch.object(fake, "_write_output_artifact", return_value="https://x"), \
         patch.object(fake, "_send_result") as sr:
        _underlying(fake.fake_engine_run)(msg)
    props = sr.call_args[0][4]
    assert "traceparent" not in props
