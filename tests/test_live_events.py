"""Tests for live progress event payloads and SignalR projection behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

import orchestrator.functions.fanout as fanout
from runtime import events


_http_terminate = fanout.http_terminate._function._func.client_function


def _progress() -> dict:
    return {
        "submissionId": "batch-1",
        "batchId": "batch-1",
        "jobId": "job-1",
        "status": "running",
        "cvsCompleted": 0,
        "cvsTotal": 1,
        "runsCompleted": 0,
        "runsDispatched": 1,
        "runsTotal": 2,
        "lastUpdatedAt": "2026-05-22T12:01:00Z",
        "applications": [
            {
                "applicationId": "app-1",
                "documentId": "doc-1",
                "status": "running",
                "runsCompleted": 0,
                "runsTotal": 2,
                "lastUpdatedAt": "2026-05-22T12:01:00Z",
                "runs": [
                    {
                        "runId": "run-1",
                        "runIndex": 0,
                        "status": "dispatched",
                        "artifactCount": 0,
                        "artifactNames": [],
                        "errorMessage": None,
                    },
                    {
                        "runId": "run-2",
                        "runIndex": 1,
                        "status": "queued",
                        "artifactCount": 0,
                        "artifactNames": [],
                        "errorMessage": None,
                    },
                ],
            }
        ],
    }


@pytest.fixture()
def clear_settings_cache() -> None:
    from runtime.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_build_live_progress_event_includes_identifiers_trace_and_poll_fallback() -> None:
    event = events.build_live_progress_event(
        event_type="run.dispatched",
        progress=_progress(),
        occurred_at="2026-05-22T12:01:00Z",
        sequence=3,
        correlation_id="cid-1",
        traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
        run_id="run-1",
    )

    assert event["specVersion"] == "awr.platform.progress.v1"
    assert event["eventType"] == "run.dispatched"
    assert event["sequence"] == 3
    assert event["submission"]["batchId"] == "batch-1"
    assert event["application"]["applicationId"] == "app-1"
    assert event["run"]["runId"] == "run-1"
    assert event["trace"]["correlationId"] == "cid-1"
    assert event["fallback"] == {
        "mode": "poll",
        "pollUrl": "/assess/batch/batch-1/status",
    }


def test_project_live_progress_event_returns_poll_fallback_when_disabled(
    monkeypatch: pytest.MonkeyPatch, clear_settings_cache
) -> None:
    monkeypatch.setenv("LIVE_PROGRESS_ENABLED", "false")

    with patch.object(events, "_post_to_signalr_group") as post_to_signalr:
        outcome = events.project_live_progress_event(
            {
                "specVersion": "awr.platform.progress.v1",
                "eventType": "run.dispatched",
                "submission": {"batchId": "batch-1"},
            }
        )

    assert outcome == {"projected": False, "reason": "disabled", "transport": "poll"}
    post_to_signalr.assert_not_called()


def test_project_live_progress_event_posts_to_signalr_group_when_enabled(
    monkeypatch: pytest.MonkeyPatch, clear_settings_cache
) -> None:
    monkeypatch.setenv("LIVE_PROGRESS_ENABLED", "true")
    monkeypatch.setenv(
        "SIGNALR_CONNECTION_STRING",
        "Endpoint=https://example.service.signalr.net;AccessKey=test-key;Version=1.0;",
    )
    monkeypatch.setenv("SIGNALR_HUB_NAME", "batch-progress")
    monkeypatch.setenv("LIVE_PROGRESS_TARGET", "batchProgress")
    monkeypatch.setenv("LIVE_PROGRESS_GROUP_PREFIX", "submission")

    captured: dict = {}

    def fake_post(*, url: str, bearer_token: str, body: dict) -> None:
        captured["url"] = url
        captured["bearer_token"] = bearer_token
        captured["body"] = body

    event = events.build_live_progress_event(
        event_type="run.dispatched",
        progress=_progress(),
        occurred_at="2026-05-22T12:01:00Z",
        sequence=1,
        correlation_id="cid-1",
        traceparent="",
        run_id="run-1",
    )

    with patch.object(events, "_post_to_signalr_group", side_effect=fake_post):
        outcome = events.project_live_progress_event(event)

    assert outcome == {"projected": True, "transport": "signalr"}
    assert captured["url"] == "https://example.service.signalr.net/api/v1/hubs/batch-progress/groups/submission:batch-1"
    assert captured["bearer_token"]
    assert captured["body"]["target"] == "batchProgress"
    assert captured["body"]["arguments"] == [event]


def test_project_live_progress_event_uses_managed_identity_when_endpoint_configured(
    monkeypatch: pytest.MonkeyPatch, clear_settings_cache
) -> None:
    monkeypatch.setenv("LIVE_PROGRESS_ENABLED", "true")
    monkeypatch.setenv("SIGNALR_SERVICE_ENDPOINT", "https://example.service.signalr.net")

    captured: dict = {}

    def fake_post(*, url: str, bearer_token: str, body: dict) -> None:
        captured["url"] = url
        captured["bearer_token"] = bearer_token
        captured["body"] = body

    event = events.build_live_progress_event(
        event_type="run.dispatched",
        progress=_progress(),
        occurred_at="2026-05-22T12:01:00Z",
        sequence=5,
        correlation_id="cid-1",
        traceparent="",
        run_id="run-1",
    )

    with patch.object(events, "_build_signalr_managed_identity_bearer_token", return_value="aad-token"), \
         patch.object(events, "_post_to_signalr_group", side_effect=fake_post):
        outcome = events.project_live_progress_event(event)

    assert outcome == {"projected": True, "transport": "signalr"}
    assert captured["url"] == "https://example.service.signalr.net/api/v1/hubs/batch-progress/groups/submission:batch-1"
    assert captured["bearer_token"] == "aad-token"
    assert captured["body"]["arguments"] == [event]


def test_project_live_progress_event_falls_back_to_poll_on_signalr_error(
    monkeypatch: pytest.MonkeyPatch, clear_settings_cache
) -> None:
    monkeypatch.setenv("LIVE_PROGRESS_ENABLED", "true")
    monkeypatch.setenv(
        "SIGNALR_CONNECTION_STRING",
        "Endpoint=https://example.service.signalr.net;AccessKey=test-key;Version=1.0;",
    )

    event = events.build_live_progress_event(
        event_type="run.dispatched",
        progress=_progress(),
        occurred_at="2026-05-22T12:01:00Z",
        sequence=2,
        correlation_id="cid-1",
        traceparent="",
        run_id="run-1",
    )

    with patch.object(events, "_post_to_signalr_group", side_effect=events.httpx.HTTPError("boom")):
        outcome = events.project_live_progress_event(event)

    assert outcome == {"projected": False, "reason": "signalr-error", "transport": "poll"}


def test_project_live_progress_event_links_span_to_traceparent(
    monkeypatch: pytest.MonkeyPatch, clear_settings_cache
) -> None:
    monkeypatch.setenv("LIVE_PROGRESS_ENABLED", "true")
    monkeypatch.setenv(
        "SIGNALR_CONNECTION_STRING",
        "Endpoint=https://example.service.signalr.net;AccessKey=test-key;Version=1.0;",
    )

    trace_id_hex = "0123456789abcdef0123456789abcdef"
    span_id_hex = "fedcba9876543210"
    traceparent = f"00-{trace_id_hex}-{span_id_hex}-01"
    event = events.build_live_progress_event(
        event_type="run.dispatched",
        progress=_progress(),
        occurred_at="2026-05-22T12:01:00Z",
        sequence=4,
        correlation_id="cid-1",
        traceparent=traceparent,
        run_id="run-1",
    )

    captured: dict = {}
    real_start = events._tracer.start_as_current_span

    def _spy(name, links=None, **kw):  # noqa: ANN001
        captured["name"] = name
        captured["links"] = list(links or [])
        return real_start(name, links=links, **kw)

    with patch.object(events, "_post_to_signalr_group", return_value=None), \
         patch.object(events._tracer, "start_as_current_span", side_effect=_spy):
        outcome = events.project_live_progress_event(event)

    assert outcome == {"projected": True, "transport": "signalr"}
    assert captured["name"] == "live_progress.project"
    assert len(captured["links"]) == 1
    link_ctx = captured["links"][0].context
    assert f"{link_ctx.trace_id:032x}" == trace_id_hex
    assert f"{link_ctx.span_id:016x}" == span_id_hex


def test_project_live_progress_activity_delegates_to_runtime_projector() -> None:
    payload = {"eventType": "run.dispatched", "submission": {"batchId": "batch-1"}}

    with patch("orchestrator.functions.fanout.project_live_progress_event") as projector:
        projector.return_value = {"projected": True, "transport": "signalr"}
        outcome = fanout.project_live_progress(payload)

    assert outcome == {"projected": True, "transport": "signalr"}
    projector.assert_called_once_with(payload)


def test_build_run_completed_live_event_prefers_result_trace_context() -> None:
    result_traceparent = "00-" + "3" * 32 + "-" + "4" * 16 + "-01"

    event = fanout._build_run_completed_live_event(  # type: ignore[attr-defined]
        progress=_progress(),
        occurred_at="2026-05-22T12:02:00Z",
        sequence=6,
        default_correlation_id="cid-default",
        default_traceparent="00-" + "1" * 32 + "-" + "2" * 16 + "-01",
        run_result={
            "run_id": "run-1",
            "artifacts": [{"name": "output.json"}],
            "correlation_id": "cid-result",
            "traceparent": result_traceparent,
        },
    )

    assert event["eventType"] == "run.completed"
    assert event["trace"]["correlationId"] == "cid-result"
    assert event["trace"]["traceparent"] == result_traceparent
    assert event["run"]["runId"] == "run-1"


def test_build_run_completed_live_event_falls_back_to_batch_trace_context() -> None:
    event = fanout._build_run_completed_live_event(  # type: ignore[attr-defined]
        progress=_progress(),
        occurred_at="2026-05-22T12:02:00Z",
        sequence=7,
        default_correlation_id="cid-default",
        default_traceparent="00-" + "1" * 32 + "-" + "2" * 16 + "-01",
        run_result={
            "run_id": "run-1",
            "artifacts": [],
        },
    )

    assert event["trace"]["correlationId"] == "cid-default"
    assert event["trace"]["traceparent"] == "00-" + "1" * 32 + "-" + "2" * 16 + "-01"


def test_build_run_terminal_live_event_uses_failed_taxonomy_and_emits_application_completion() -> None:
    progress = _progress()
    progress["applications"][0]["runs"] = [
        {
            "runId": "run-1",
            "runIndex": 0,
            "status": "failed",
            "artifactCount": 0,
            "artifactNames": [],
            "errorMessage": "boom",
        },
        {
            "runId": "run-2",
            "runIndex": 1,
            "status": "succeeded",
            "artifactCount": 1,
            "artifactNames": ["output.json"],
            "errorMessage": None,
        },
    ]
    progress["applications"][0]["status"] = "partial"
    progress["applications"][0]["runsCompleted"] = 2

    run_event = fanout._build_run_terminal_live_event(  # type: ignore[attr-defined]
        progress=progress,
        occurred_at="2026-05-22T12:02:00Z",
        sequence=8,
        default_correlation_id="cid-default",
        default_traceparent="00-" + "1" * 32 + "-" + "2" * 16 + "-01",
        run_result={
            "run_id": "run-1",
            "status": "Failed",
            "artifacts": [],
            "error_message": "boom",
        },
    )
    application_event = fanout._build_application_terminal_live_event(  # type: ignore[attr-defined]
        progress=progress,
        occurred_at="2026-05-22T12:02:00Z",
        sequence=9,
        correlation_id="cid-default",
        traceparent="00-" + "1" * 32 + "-" + "2" * 16 + "-01",
        application_id="app-1",
    )

    assert run_event["eventType"] == "run.failed"
    assert run_event["run"]["status"] == "failed"
    assert application_event["eventType"] == "application.completed"
    assert application_event["application"]["applicationId"] == "app-1"
    assert application_event["application"]["status"] == "partial"


@pytest.mark.asyncio
async def test_http_terminate_projects_batch_cancelling_event() -> None:
    req = SimpleNamespace(
        route_params={"instance_id": "batch-1"},
        get_json=lambda: {"reason": "operator request"},
    )
    client = SimpleNamespace(
        get_status=AsyncMock(
            return_value=SimpleNamespace(
                runtime_status=fanout.df.OrchestrationRuntimeStatus.Running,
                custom_status=_progress(),
            )
        ),
        terminate=AsyncMock(),
    )

    with patch("orchestrator.functions.fanout.project_live_progress_event") as projector:
        resp = await _http_terminate(req, client=client)

    assert resp.status_code == 202
    client.terminate.assert_awaited_once_with("batch-1", "operator request")
    projector.assert_called_once()
    event = projector.call_args.args[0]
    assert event["eventType"] == "batch.cancelling"
    assert event["submission"]["batchId"] == "batch-1"
    assert event["submission"]["status"] == "cancelling"


@pytest.mark.asyncio
async def test_http_terminate_projects_batch_cancelled_event_when_already_terminated() -> None:
    req = SimpleNamespace(
        route_params={"instance_id": "batch-1"},
        get_json=lambda: {"reason": "operator request"},
    )
    client = SimpleNamespace(
        get_status=AsyncMock(
            return_value=SimpleNamespace(
                runtime_status=fanout.df.OrchestrationRuntimeStatus.Terminated,
                custom_status=_progress(),
            )
        ),
        terminate=AsyncMock(),
    )

    with patch("orchestrator.functions.fanout.project_live_progress_event") as projector:
        resp = await _http_terminate(req, client=client)

    assert resp.status_code == 200
    client.terminate.assert_not_called()
    projector.assert_called_once()
    event = projector.call_args.args[0]
    assert event["eventType"] == "batch.cancelled"
    assert event["submission"]["batchId"] == "batch-1"
    assert event["submission"]["status"] == "cancelled"