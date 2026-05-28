"""Live E2E verification with prompt4 and three real CV PDFs.

This test is opt-in and performs a real submission against the deployed platform.
It stages the three PDFs from tests/realdata to blob storage, submits one batch,
and validates completed aggregation for all three CVs.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest


REALDATA_DIR = Path(__file__).parent / "realdata"
PROMPT_FILE = REALDATA_DIR / "prompt4.txt"
CV_FILES = [
    REALDATA_DIR / "Candidate_A_Perfect_Fit_Principal_FULL_BEHAVIOURAL.pdf",
    REALDATA_DIR / "Candidate_B_Good_Fit_Principal.pdf",
    REALDATA_DIR / "Candidate_C_Chancer_Principal.pdf",
]


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"{name} is required for real 3-CV E2E test")
    return value


def _stage_pdf(storage_account: str, container: str, pdf_path: Path) -> tuple[str, str]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"missing test asset: {pdf_path}")

    sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    blob_name = f"realdata/{pdf_path.stem}-{sha256[:12]}.pdf"
    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient, ContentSettings
    except Exception as exc:  # pragma: no cover - dependency gating
        pytest.skip(f"Azure SDK dependencies not available for staging: {exc}")

    account_url = f"https://{storage_account}.blob.core.windows.net"
    blob_service = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
    container_client = blob_service.get_container_client(container)
    try:
        container_client.create_container()
    except Exception:
        # Container often already exists in shared QA environments.
        pass

    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(
        pdf_path.read_bytes(),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/pdf"),
    )

    blob_uri = f"https://{storage_account}.blob.core.windows.net/{container}/{blob_name}"
    return blob_uri, sha256


def test_real_engine_prompt4_three_real_cvs_are_aggregated() -> None:
    if os.getenv("RUN_REAL_ENGINE_E2E", "false").lower() not in {"1", "true", "yes"}:
        pytest.skip("Set RUN_REAL_ENGINE_E2E=true to run live real-engine 3-CV validation")

    base_url = _env("REAL_ENGINE_E2E_BASE_URL").rstrip("/")
    storage_account = _env("REAL_ENGINE_E2E_STORAGE_ACCOUNT")
    container = os.getenv("REAL_ENGINE_E2E_STORAGE_CONTAINER", "cv-uploads").strip() or "cv-uploads"
    run_count = int(os.getenv("REAL_ENGINE_E2E_RUN_COUNT", "1"))
    timeout_seconds = int(os.getenv("REAL_ENGINE_E2E_TIMEOUT_SECONDS", "600"))
    poll_seconds = int(os.getenv("REAL_ENGINE_E2E_POLL_SECONDS", "5"))

    prompt_text = PROMPT_FILE.read_text(encoding="utf-8").strip()
    assert prompt_text, "prompt4.txt must not be empty"

    staged_cvs: list[dict[str, Any]] = []
    for idx, pdf in enumerate(CV_FILES, start=1):
        blob_uri, sha256 = _stage_pdf(storage_account=storage_account, container=container, pdf_path=pdf)
        staged_cvs.append(
            {
                "applicationId": f"app-{idx}",
                "documentId": f"doc-{idx}",
                "fileName": pdf.name,
                "mimeType": "application/pdf",
                "blobUri": blob_uri,
                "sha256": sha256,
            }
        )

    batch_id = str(uuid.uuid4())
    payload = {
        "batchId": batch_id,
        "jobId": f"job-real3-{batch_id[:8]}",
        "promptVersionId": "pv-realdata-prompt4",
        "runCount": run_count,
        "prompt": {
            "kind": "inline",
            "text": prompt_text,
        },
        "cvs": staged_cvs,
    }

    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": batch_id,
        "x-correlation-id": f"real3-{batch_id}",
    }

    api_key = os.getenv("REAL_ENGINE_E2E_APIM_KEY", "").strip()
    bearer = os.getenv("REAL_ENGINE_E2E_BEARER", "").strip()
    if api_key:
        headers["Ocp-Apim-Subscription-Key"] = api_key
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    with httpx.Client(timeout=60.0) as client:
        submit = client.post(f"{base_url}/assess/batch", json=payload, headers=headers)
        assert submit.status_code == 202, submit.text

        submit_json = submit.json()
        assert submit_json.get("submissionId") == batch_id

        deadline = time.time() + timeout_seconds
        last_response: dict[str, Any] = {}
        while time.time() < deadline:
            time.sleep(poll_seconds)
            status_resp = client.get(f"{base_url}/assess/batch/{batch_id}/status", headers=headers)
            assert status_resp.status_code == 200, status_resp.text
            last_response = status_resp.json()
            if last_response.get("status") in {"completed", "failed", "cancelled"}:
                break

    assert last_response, "No status response captured"
    assert last_response.get("status") == "completed", json.dumps(last_response, indent=2)

    result = last_response.get("result")
    assert isinstance(result, dict), last_response
    cvs = result.get("cvs")
    assert isinstance(cvs, list) and len(cvs) == 3, result

    by_app = {cv.get("applicationId"): cv for cv in cvs}
    for expected in staged_cvs:
        app_id = expected["applicationId"]
        assert app_id in by_app, by_app
        cv = by_app[app_id]
        aggregated = cv.get("aggregated")
        assert isinstance(aggregated, dict), cv
        assert aggregated.get("finalScore") is not None, aggregated
        assert aggregated.get("finalDecision") is not None, aggregated
        assert aggregated.get("mustHaveResult") is not None, aggregated

        runs = cv.get("runs")
        assert isinstance(runs, list) and runs, cv
        assert any(run.get("status") == "Succeeded" for run in runs), cv
