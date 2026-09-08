#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="$ROOT/release/kaggle"
DATASET_ID="taeyangg4/south-korea-customs-trade-hsk10"

python - "$ROOT" "$RELEASE_DIR" "$DATASET_ID" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
release = Path(sys.argv[2])
expected_id = sys.argv[3]

qa_path = root / "data" / "audits" / "release_qa" / "release_qa.json"
metadata_path = release / "dataset-metadata.json"
manifest_path = release / "release_manifest.json"

for path in (qa_path, metadata_path, manifest_path):
    if not path.exists():
        raise SystemExit(f"missing required file: {path}")

qa = json.loads(qa_path.read_text(encoding="utf-8"))
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

if qa.get("release_gate_pass") is not True:
    raise SystemExit("release QA has not passed; refusing Kaggle upload")
if metadata.get("id") != expected_id:
    raise SystemExit(f"unexpected dataset id: {metadata.get('id')!r}")
if manifest.get("quality", {}).get("release_gate_pass") is not True:
    raise SystemExit("release manifest does not record a passing release gate")

coverage = manifest.get("coverage", {})
print("[12/12] Kaggle private-upload preflight PASS")
print(f"dataset_id={expected_id}")
print(f"coverage={coverage.get('start_month')}..{coverage.get('end_month')}")
print(f"canonical_hsk10_rows={coverage.get('canonical_hsk10_rows')}")
print(f"release_files={len(list(release.iterdir()))}")
PY

if [[ "${1:-}" == "--preflight-only" ]]; then
  echo "[12/12] Preflight-only mode complete; no upload was attempted."
  exit 0
fi

echo "[12/12] Creating Kaggle dataset privately (no --public flag)..."
kaggle datasets create -p "$RELEASE_DIR" -t

echo "[12/12] Kaggle dataset create command finished. Current status:"
kaggle datasets status "$DATASET_ID" --format json
