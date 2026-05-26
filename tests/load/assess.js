// k6 load script for POST /assess/batch.
//
// Run against a deployed platform with the fake-engine consuming engine-runs.
// Each iteration submits one batch with a unique batchId and polls status
// until completion (or timeout). No LLM tokens consumed.
//
// Usage:
//   k6 run \
//     -e BASE_URL=https://<apim-host>/awr \
//     -e API_KEY=<apim-subscription-key> \
//     -e CV_BLOB_URI=https://<acct>.blob.core.windows.net/cv-uploads/sample.pdf \
//     -e CV_SHA256=<64-hex-sha> \
//     tests/load/assess.js
//
// Tune load:
//   --vus 20 --duration 5m         constant load
//   -e RUN_COUNT=3 -e CV_COUNT=5   batch shape
//   -e POLL=true                   include status polling per iteration

import http from 'k6/http';
import { check, sleep, fail } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';
import { Trend, Rate, Counter } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const API_KEY = __ENV.API_KEY || '';
const BEARER = __ENV.BEARER || '';
const CV_BLOB_URI = __ENV.CV_BLOB_URI || 'https://example.blob.core.windows.net/cv-uploads/sample.pdf';
const CV_SHA256 = __ENV.CV_SHA256 || 'a'.repeat(64);
const RUN_COUNT = parseInt(__ENV.RUN_COUNT || '1', 10);
const CV_COUNT = parseInt(__ENV.CV_COUNT || '1', 10);
const POLL = (__ENV.POLL || 'false').toLowerCase() === 'true';
const POLL_TIMEOUT_S = parseInt(__ENV.POLL_TIMEOUT_S || '120', 10);
const POLL_INTERVAL_S = parseInt(__ENV.POLL_INTERVAL_S || '3', 10);

export const options = {
  scenarios: {
    soak: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 5 },
        { duration: '2m',  target: 20 },
        { duration: '2m',  target: 50 },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    'http_req_failed{endpoint:submit}': ['rate<0.01'],
    'http_req_duration{endpoint:submit}': ['p(95)<800', 'p(99)<2000'],
    'http_req_duration{endpoint:status}': ['p(95)<400'],
    batch_completed_rate: ['rate>0.95'],
    batch_e2e_seconds: ['p(95)<60'],
  },
};

const submitDuration = new Trend('submit_duration_ms');
const e2eDuration   = new Trend('batch_e2e_seconds');
const completedRate = new Rate('batch_completed_rate');
const submitErrors  = new Counter('submit_errors');

function buildPayload(batchId) {
  const cvs = [];
  for (let i = 0; i < CV_COUNT; i++) {
    cvs.push({
      applicationId: `app-${batchId}-${i}`,
      documentId:    `doc-${batchId}-${i}`,
      fileName:      `cv-${i}.pdf`,
      mimeType:      'application/pdf',
      blobUri:       CV_BLOB_URI,
      sha256:        CV_SHA256,
    });
  }
  return {
    batchId,
    jobId: `job-${batchId.slice(0, 8)}`,
    promptVersionId: 'pv-1',
    runCount: RUN_COUNT,
    prompt: { kind: 'inline', text: 'Score this candidate against the spec.' },
    cvs,
  };
}

function headers(batchId, traceparent) {
  const h = {
    'Content-Type': 'application/json',
    'Idempotency-Key': batchId,
    'x-correlation-id': batchId,
  };
  if (traceparent) h['traceparent'] = traceparent;
  if (API_KEY) h['Ocp-Apim-Subscription-Key'] = API_KEY;
  if (BEARER)  h['Authorization'] = `Bearer ${BEARER}`;
  return h;
}

function newTraceparent() {
  // 00-<32hex>-<16hex>-01
  const hex = (n) => Array.from({ length: n }, () => Math.floor(Math.random() * 16).toString(16)).join('');
  return `00-${hex(32)}-${hex(16)}-01`;
}

export default function () {
  const batchId = uuidv4();
  const traceparent = newTraceparent();
  const t0 = Date.now();

  const submitRes = http.post(
    `${BASE_URL}/assess/batch`,
    JSON.stringify(buildPayload(batchId)),
    { headers: headers(batchId, traceparent), tags: { endpoint: 'submit' } },
  );
  submitDuration.add(submitRes.timings.duration);

  const ok = check(submitRes, {
    'submit 202': (r) => r.status === 202,
    'submit body has submissionId': (r) => {
      try { return JSON.parse(r.body).submissionId === batchId; } catch { return false; }
    },
  });
  if (!ok) {
    submitErrors.add(1);
    return;
  }

  if (!POLL) return;

  const deadline = t0 + POLL_TIMEOUT_S * 1000;
  let terminal = false;
  while (Date.now() < deadline) {
    sleep(POLL_INTERVAL_S);
    const statusRes = http.get(
      `${BASE_URL}/assess/batch/${batchId}/status`,
      { headers: headers(batchId), tags: { endpoint: 'status' } },
    );
    if (statusRes.status !== 200) continue;
    let body;
    try { body = JSON.parse(statusRes.body); } catch { continue; }
    if (body.status === 'completed' || body.status === 'failed' || body.status === 'cancelled') {
      terminal = true;
      completedRate.add(body.status === 'completed');
      e2eDuration.add((Date.now() - t0) / 1000);
      break;
    }
  }
  if (!terminal) {
    completedRate.add(false);
    fail(`batch ${batchId} did not reach terminal state within ${POLL_TIMEOUT_S}s`);
  }
}
