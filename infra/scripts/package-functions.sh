#!/usr/bin/env bash
# ── package-functions.sh ──────────────────────────────────────────────────────
# Build a deployment zip for the Azure Functions Python v2 app at the repo root.
# Includes: function_app.py, host.json, requirements.txt + orchestrator/runtime/db
# Excludes: __pycache__, *.pyc, tests/, .venv, local.settings.json
#
# Usage:
#   ./infra/scripts/package-functions.sh                  # → dist/functions.zip
#   ./infra/scripts/package-functions.sh path/to/out.zip
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

OUT="${1:-$REPO_ROOT/dist/functions.zip}"
mkdir -p "$(dirname "$OUT")"

# Convert MSYS path to native Windows path when running under Git Bash so the
# Windows-native python interpreter can open the output file.
if command -v cygpath >/dev/null 2>&1; then
  OUT_NATIVE="$(cygpath -w "$OUT")"
else
  OUT_NATIVE="$OUT"
fi

cd "$REPO_ROOT"

INCLUDE_FILES=(function_app.py host.json requirements.txt)
INCLUDE_DIRS=(orchestrator runtime db)

for f in "${INCLUDE_FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: required file missing: $f" >&2
    exit 1
  fi
done

# Build with python's zipfile for portable behaviour and deterministic excludes.
PYBIN="$(command -v python3 || command -v python)"
"$PYBIN" - "$OUT_NATIVE" "${INCLUDE_FILES[@]}" -- "${INCLUDE_DIRS[@]}" <<'PY'
import os, sys, zipfile

argv = sys.argv[1:]
out = argv[0]
sep = argv.index('--')
files = argv[1:sep]
dirs  = argv[sep+1:]

EXCLUDE_DIRS = {'__pycache__', '.pytest_cache', '.mypy_cache', 'tests'}

if os.path.exists(out):
    os.remove(out)

with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(f, f)
    for d in dirs:
        for root, subdirs, names in os.walk(d):
            subdirs[:] = [s for s in subdirs if s not in EXCLUDE_DIRS]
            for n in names:
                if n.endswith(('.pyc', '.pyo')):
                    continue
                p = os.path.join(root, n)
                arc = p.replace('\\', '/')
                z.write(p, arc)

print(f"OUT={out}")
print(f"size={os.path.getsize(out)} bytes")
PY

echo "✓ Wrote $OUT"
