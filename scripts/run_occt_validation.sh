#!/usr/bin/env bash
# Phase 3A/3B/3C OCCT worker validation.
#
# Run on a machine with `pythonocc-core==7.8.1.1` installed (conda-forge).
# Produces three artifacts per sample:
#   out/occt_validation/<sample>/book.pdf
#   out/occt_validation/<sample>/metadata/geometry_runtime_summary.json
#   out/occt_validation/<sample>/metadata/view_geometry.json
# and runs the runtime acceptance gate (non-zero on violations).
#
# Usage:
#   bash scripts/run_occt_validation.sh                 # small + medium
#   bash scripts/run_occt_validation.sh --include-large # + Hochvolthaus
# Optional thresholds (env vars):
#   MAX_FALLBACK_EVENT_RATE=0.20
#   MAX_TIMEOUT_EVENTS_TOTAL=0
#   MIN_OCCT_COVERAGE_RATE=0.50
#   MIN_HIDDEN_LINES_TOTAL=100
#   MIN_HIDDEN_LINE_RATIO=0.05
# Optional profile (env var):
#   PROFILE_PATH=ifc_book_prototype/profiles/din_iso_arch_floor_plan_v3_phase3c_owned_projection.json
set -euo pipefail

cd "$(dirname "$0")/.."

export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export TZ=UTC
export PYTHONHASHSEED=0
export SOURCE_DATE_EPOCH=0

OUT_ROOT="out/occt_validation"
mkdir -p "$OUT_ROOT"
MAX_FALLBACK_EVENT_RATE="${MAX_FALLBACK_EVENT_RATE:-0.20}"
MAX_TIMEOUT_EVENTS_TOTAL="${MAX_TIMEOUT_EVENTS_TOTAL:-0}"
MIN_OCCT_COVERAGE_RATE="${MIN_OCCT_COVERAGE_RATE:-0.50}"
MIN_HIDDEN_LINES_TOTAL="${MIN_HIDDEN_LINES_TOTAL:-}"
MIN_HIDDEN_LINE_RATIO="${MIN_HIDDEN_LINE_RATIO:-}"
PROFILE_PATH="${PROFILE_PATH:-ifc_book_prototype/profiles/din_iso_arch_floor_plan_v3_phase3c_owned_projection.json}"
ANY_GATE_FAIL=0

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
  echo "profile=$PROFILE_PATH"
  rm -rf "$run_dir"
  started_at="$(date +%s)"
  python -m ifc_book_prototype.cli "$ifc" --out "$run_dir" --profile "$PROFILE_PATH"
  finished_at="$(date +%s)"
  runtime_s="$((finished_at - started_at))"
  python - <<'PY' "$run_dir" "$runtime_s"
import json
import pathlib
import sys

run_dir = pathlib.Path(sys.argv[1])
runtime_s = float(sys.argv[2])
path = run_dir / "metadata" / "benchmark_runtime.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(
    json.dumps({"pipeline_runtime_s": runtime_s}, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
    encoding="utf-8",
)
PY
  python -m ifc_book_prototype.cli --summarize-runtime "$run_dir"
  gate_args=(
    --runtime-gate "$run_dir"
    --max-fallback-event-rate "$MAX_FALLBACK_EVENT_RATE"
    --max-timeout-events-total "$MAX_TIMEOUT_EVENTS_TOTAL"
    --min-occt-coverage-rate "$MIN_OCCT_COVERAGE_RATE"
  )
  if [[ -n "$MIN_HIDDEN_LINES_TOTAL" ]]; then
    gate_args+=(--min-hidden-lines-total "$MIN_HIDDEN_LINES_TOTAL")
  fi
  if [[ -n "$MIN_HIDDEN_LINE_RATIO" ]]; then
    gate_args+=(--min-hidden-line-ratio "$MIN_HIDDEN_LINE_RATIO")
  fi
  set +e
  gate_output="$(
    python -m ifc_book_prototype.cli "${gate_args[@]}"
  )"
  gate_rc=$?
  set -e
  echo "$gate_output"
  gate_json="$(printf '%s\n' "$gate_output" | grep '^RUNTIME_GATE_JSON=' | sed 's/^RUNTIME_GATE_JSON=//')"
  if [[ -n "$gate_json" ]]; then
    printf '%s\n' "$gate_json" > "$run_dir/metadata/runtime_gate_result.json"
  fi
  if [[ "$gate_rc" -ne 0 ]]; then
    ANY_GATE_FAIL=1
  fi
  echo
done

python -m ifc_book_prototype.benchmark "$OUT_ROOT"
python -m ifc_book_prototype.cli \
  --plan-next "$OUT_ROOT" \
  --plan-next-out "$OUT_ROOT/next_steps.md" \
  --plan-next-json-out "$OUT_ROOT/next_steps.json" \
  --plan-next-svg-out "$OUT_ROOT/next_steps.svg"

if [[ "$ANY_GATE_FAIL" -ne 0 ]]; then
  echo "One or more samples failed runtime gate thresholds."
  exit 1
fi

echo "Done. Re-run the determinism gate to confirm byte-identity:"
echo "  pytest tests/test_determinism.py -q -m 'not slow'"
