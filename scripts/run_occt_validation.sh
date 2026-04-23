#!/usr/bin/env bash
# Phase 3A/3B/3C OCCT worker validation.
#
# Run on a machine with `pythonocc-core==7.8.1.1` installed (conda-forge).
# Produces three artifacts per sample:
#   out/occt_validation/<sample>/book.pdf
#   out/occt_validation/<sample>/metadata/geometry_runtime_summary.json
#   out/occt_validation/<sample>/metadata/view_geometry.json
# and prints a terse summary so the operator can paste results into
# PHASE3A_VALIDATION.md.
#
# Usage:
#   bash scripts/run_occt_validation.sh                 # small + medium
#   bash scripts/run_occt_validation.sh --include-large # + Hochvolthaus
set -euo pipefail

cd "$(dirname "$0")/.."

export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export TZ=UTC
export PYTHONHASHSEED=0
export SOURCE_DATE_EPOCH=0

OUT_ROOT="out/occt_validation"
mkdir -p "$OUT_ROOT"

SAMPLES=(
  "samples/Building-Architecture.ifc"
  "samples/demo.ifc"
)
if [[ "${1:-}" == "--include-large" ]]; then
  SAMPLES+=("samples/new251211_Hochvolthaus_Group01_03.ifc")
fi

python -c "from ifc_book_prototype import occt_section; \
  print(f'OCCT_AVAILABLE={occt_section.OCCT_AVAILABLE}')"

for ifc in "${SAMPLES[@]}"; do
  name="$(basename "$ifc" .ifc)"
  run_dir="$OUT_ROOT/$name"
  echo "=== $name ==="
  rm -rf "$run_dir"
  python -m ifc_book_prototype.cli "$ifc" --out "$run_dir"
  python -m ifc_book_prototype.cli --summarize-runtime "$run_dir"
  echo
done

echo "Done. Re-run the determinism gate to confirm byte-identity:"
echo "  pytest tests/test_determinism.py -q -m 'not slow'"
