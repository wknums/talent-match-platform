#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Pre-stage a CV blob for load tests.
#
# Uploads a sample PDF (or any file) to the platform's CV container and prints
# the values you need for the k6 script: CV_BLOB_URI and CV_SHA256.
#
# Usage:
#   ./scripts/stage-cv.sh <storage-account> [container] [path-to-file]
#
# Examples:
#   ./scripts/stage-cv.sh <storage-account>
#   ./scripts/stage-cv.sh <storage-account> cv-uploads ./samples/sample-cv.pdf
#
# If no file is given, a tiny synthetic PDF is generated.
# Requires: az CLI (logged in), openssl, sha256sum.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
export MSYS_NO_PATHCONV=1

STORAGE_ACCOUNT="${1:?Usage: stage-cv.sh <storage-account> [container] [file]}"
CONTAINER="${2:-cv-uploads}"
FILE="${3:-}"

# Generate a tiny PDF if none provided.
if [[ -z "$FILE" ]]; then
  FILE="$(mktemp --suffix=.pdf)"
  cat > "$FILE" <<'PDF'
%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<<>>>>endobj
4 0 obj<</Length 44>>stream
BT /F1 18 Tf 72 720 Td (AWR Load Test Sample CV) Tj ET
endstream endobj
xref
0 5
0000000000 65535 f
0000000010 00000 n
0000000053 00000 n
0000000095 00000 n
0000000175 00000 n
trailer<</Size 5/Root 1 0 R>>
startxref
259
%%EOF
PDF
  echo "Generated synthetic PDF at $FILE"
fi

if [[ ! -f "$FILE" ]]; then
  echo "ERROR: file not found: $FILE" >&2
  exit 1
fi

# Filename in blob storage: cv-loadtest-<sha8>.pdf — deterministic and reusable.
SHA256="$(sha256sum "$FILE" | awk '{print $1}')"
SHA8="${SHA256:0:8}"
BLOB_NAME="loadtest/cv-${SHA8}.pdf"

echo "Ensuring container '$CONTAINER' on $STORAGE_ACCOUNT..."
az storage container create \
  --account-name "$STORAGE_ACCOUNT" \
  --name "$CONTAINER" \
  --auth-mode login \
  -o none

echo "Uploading $FILE → $CONTAINER/$BLOB_NAME ..."
az storage blob upload \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --name "$BLOB_NAME" \
  --file "$FILE" \
  --content-type "application/pdf" \
  --overwrite \
  --auth-mode login \
  -o none

BLOB_URI="https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER}/${BLOB_NAME}"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  CV staged."
echo "═══════════════════════════════════════════════════════════"
echo "  CV_BLOB_URI=${BLOB_URI}"
echo "  CV_SHA256=${SHA256}"
echo ""
echo "  k6 command:"
echo "    k6 run \\"
echo "      -e BASE_URL=<platform-url> \\"
echo "      -e CV_BLOB_URI=${BLOB_URI} \\"
echo "      -e CV_SHA256=${SHA256} \\"
echo "      tests/load/assess.js"
echo ""
