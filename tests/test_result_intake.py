"""Tests for the result-intake handlers (SB-trigger + PATCH /runs/{id}).

Both paths look up the owning batch via the run-index blob and raise the
``run-{run_id}`` Durable external event.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import orchestrator.functions.result_intake as result_intake
from orchestrator.sb_contracts import RunResultMessage

# Blueprint decorators wrap into FunctionBuilder; reach the original user fn.
_sb_result_handler = result_intake.sb_result_handler._function._func.client_function
_http_patch_run = result_intake.http_patch_run._function._func.client_function


@pytest.fixture()
def settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLOB_ACCOUNT", "acct")
    monkeypatch.setenv("BLOB_RESULTS_CONTAINER", "batch-results")
    from runtime.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]


def _result_msg_json(run_id: str = "r1") -> str:
    return json.dumps({
        "run_id": run_id,
        "status": "Succeeded",
        "duration_ms": 1234,
        "tokens_prompt": 100,
        "tokens_completion": 50,
        "error_message": None,
        "correlation_id": "cid-1",
        "artifacts": None,
    })


# ── SB trigger ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sb_result_handler_raises_event_with_traceparent(settings) -> None:
    msg = MagicMock()
    msg.get_body.return_value = _result_msg_json("r1").encode("utf-8")
    msg.application_properties = {"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01"}

    client = MagicMock()
    client.raise_event = AsyncMock()

    with patch.object(result_intake, "_lookup_batch_id", return_value="b1"), \
         patch.object(result_intake, "_claim_result_delivery", return_value=True):
        await _sb_result_handler(msg, client=client)

    client.raise_event.assert_awaited_once()
    args, _ = client.raise_event.call_args
    assert args[0] == "b1"
    assert args[1] == "run-r1"
    assert args[2]["run_id"] == "r1"
    assert args[2]["status"] == "Succeeded"
    assert args[2]["traceparent"].startswith("00-")


@pytest.mark.asyncio
async def test_sb_result_handler_unknown_run_id_is_dropped(settings) -> None:
    msg = MagicMock()
    msg.get_body.return_value = _result_msg_json("r-orphan").encode("utf-8")
    msg.application_properties = {}
    client = MagicMock()
    client.raise_event = AsyncMock()

    with patch.object(result_intake, "_lookup_batch_id", return_value=None):
        await _sb_result_handler(msg, client=client)

    client.raise_event.assert_not_called()


@pytest.mark.asyncio
async def test_sb_result_handler_invalid_body_raises(settings) -> None:
    msg = MagicMock()
    msg.get_body.return_value = b"{not json"
    client = MagicMock()

    with pytest.raises(Exception):
        await _sb_result_handler(msg, client=client)


# ── HTTP PATCH ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_http_patch_run_raises_event(settings) -> None:
    req = MagicMock()
    req.route_params = {"run_id": "r1"}
    req.headers = {"x-correlation-id": "cid-1", "traceparent": "00-" + "c" * 32 + "-" + "d" * 16 + "-01"}
    req.get_json.return_value = {
        "status": "Succeeded",
        "duration_ms": 1234,
        "tokens_prompt": 100,
        "tokens_completion": 50,
        "error_message": None,
        "artifacts": None,
    }
    client = MagicMock()
    client.raise_event = AsyncMock()

    with patch.object(result_intake, "_lookup_batch_id", return_value="b1"), \
         patch.object(result_intake, "_claim_result_delivery", return_value=True):
        resp = await _http_patch_run(req, client=client)

    assert resp.status_code == 202
    args, _ = client.raise_event.call_args
    assert args[0] == "b1"
    assert args[1] == "run-r1"
    payload = args[2]
    assert payload["run_id"] == "r1"
    assert payload["correlation_id"] == "cid-1"
    assert payload["traceparent"].startswith("00-")


@pytest.mark.asyncio
async def test_http_patch_run_unknown_run_returns_404(settings) -> None:
    req = MagicMock()
    req.route_params = {"run_id": "r-missing"}
    req.headers = {}
    req.get_json.return_value = {
        "status": "Failed",
        "duration_ms": 100,
        "tokens_prompt": 0,
        "tokens_completion": 0,
        "error_message": "boom",
        "artifacts": None,
    }
    client = MagicMock()

    with patch.object(result_intake, "_lookup_batch_id", return_value=None):
        resp = await _http_patch_run(req, client=client)

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sb_result_handler_duplicate_delivery_is_dropped(settings) -> None:
    msg = MagicMock()
    msg.get_body.return_value = _result_msg_json("r1").encode("utf-8")
    msg.application_properties = {}
    client = MagicMock()
    client.raise_event = AsyncMock()

    with patch.object(result_intake, "_lookup_batch_id", return_value="b1"), \
         patch.object(result_intake, "_claim_result_delivery", return_value=False):
        await _sb_result_handler(msg, client=client)

    client.raise_event.assert_not_called()


@pytest.mark.asyncio
async def test_http_patch_run_duplicate_delivery_is_idempotent(settings) -> None:
    req = MagicMock()
    req.route_params = {"run_id": "r1"}
    req.headers = {"x-correlation-id": "cid-1"}
    req.get_json.return_value = {
        "status": "Succeeded",
        "duration_ms": 1234,
        "tokens_prompt": 100,
        "tokens_completion": 50,
        "error_message": None,
        "artifacts": None,
    }
    client = MagicMock()
    client.raise_event = AsyncMock()

    with patch.object(result_intake, "_lookup_batch_id", return_value="b1"), \
         patch.object(result_intake, "_claim_result_delivery", return_value=False):
        resp = await _http_patch_run(req, client=client)

    assert resp.status_code == 202
    client.raise_event.assert_not_called()


# ── Span linking (Phase D — observability) ───────────────────────────────────
@pytest.mark.asyncio
async def test_sb_result_handler_links_span_to_dispatch_traceparent(settings) -> None:
    """The OTel span for SB result-intake must carry a Link to the trace_id
    encoded in the inbound ``application_properties['traceparent']`` and
    expose run/batch/correlation attributes."""
    trace_id_hex = "0123456789abcdef0123456789abcdef"
    span_id_hex = "fedcba9876543210"
    tp = f"00-{trace_id_hex}-{span_id_hex}-01"

    msg = MagicMock()
    msg.get_body.return_value = _result_msg_json("r1").encode("utf-8")
    msg.application_properties = {"traceparent": tp}
    client = MagicMock()
    client.raise_event = AsyncMock()

    captured: dict = {}
    real_start = result_intake._tracer.start_as_current_span

    def _spy(name, links=None, **kw):  # noqa: ANN001
        captured["name"] = name
        captured["links"] = list(links or [])
        return real_start(name, links=links, **kw)

    with patch.object(result_intake, "_lookup_batch_id", return_value="b1"), \
         patch.object(result_intake, "_claim_result_delivery", return_value=True), \
         patch.object(result_intake._tracer, "start_as_current_span", side_effect=_spy):
        await _sb_result_handler(msg, client=client)

    assert captured["name"] == "result_intake.sb"
    assert len(captured["links"]) == 1
    link_ctx = captured["links"][0].context
    assert f"{link_ctx.trace_id:032x}" == trace_id_hex
    assert f"{link_ctx.span_id:016x}" == span_id_hex
    assert link_ctx.is_remote is True
    client.raise_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_sb_result_handler_no_links_when_traceparent_missing(settings) -> None:
    msg = MagicMock()
    msg.get_body.return_value = _result_msg_json("r1").encode("utf-8")
    msg.application_properties = {}
    client = MagicMock()
    client.raise_event = AsyncMock()

    captured: dict = {}
    real_start = result_intake._tracer.start_as_current_span

    def _spy(name, links=None, **kw):  # noqa: ANN001
        captured["links"] = list(links or [])
        return real_start(name, links=links, **kw)

    with patch.object(result_intake, "_lookup_batch_id", return_value="b1"), \
         patch.object(result_intake, "_claim_result_delivery", return_value=True), \
         patch.object(result_intake._tracer, "start_as_current_span", side_effect=_spy):
        await _sb_result_handler(msg, client=client)

    assert captured["links"] == []


@pytest.mark.asyncio
async def test_http_patch_run_links_span_to_traceparent_header(settings) -> None:
    trace_id_hex = "11112222333344445555666677778888"
    span_id_hex = "aaaabbbbccccdddd"
    tp = f"00-{trace_id_hex}-{span_id_hex}-01"

    req = MagicMock()
    req.route_params = {"run_id": "r1"}
    req.headers = {"x-correlation-id": "cid-1", "traceparent": tp}
    req.get_json.return_value = {
        "status": "Succeeded",
        "duration_ms": 1,
        "tokens_prompt": 0,
        "tokens_completion": 0,
        "error_message": None,
        "artifacts": None,
    }
    client = MagicMock()
    client.raise_event = AsyncMock()

    captured: dict = {}
    real_start = result_intake._tracer.start_as_current_span

    def _spy(name, links=None, **kw):  # noqa: ANN001
        captured["name"] = name
        captured["links"] = list(links or [])
        return real_start(name, links=links, **kw)

    with patch.object(result_intake, "_lookup_batch_id", return_value="b1"), \
         patch.object(result_intake, "_claim_result_delivery", return_value=True), \
         patch.object(result_intake._tracer, "start_as_current_span", side_effect=_spy):
        resp = await _http_patch_run(req, client=client)

    assert resp.status_code == 202
    assert captured["name"] == "result_intake.http"
    assert len(captured["links"]) == 1
    link_ctx = captured["links"][0].context
    assert f"{link_ctx.trace_id:032x}" == trace_id_hex
    assert f"{link_ctx.span_id:016x}" == span_id_hex


def test_parse_traceparent_rejects_bad_inputs() -> None:
    assert result_intake._parse_traceparent("") is None
    assert result_intake._parse_traceparent("not-a-traceparent") is None
    # Wrong version
    assert result_intake._parse_traceparent("01-" + "a" * 32 + "-" + "b" * 16 + "-01") is None
    # All-zero trace/span ids must be rejected per W3C
    assert result_intake._parse_traceparent("00-" + "0" * 32 + "-" + "b" * 16 + "-01") is None
    assert result_intake._parse_traceparent("00-" + "a" * 32 + "-" + "0" * 16 + "-01") is None
    # Non-hex
    assert result_intake._parse_traceparent("00-" + "z" * 32 + "-" + "b" * 16 + "-01") is None
