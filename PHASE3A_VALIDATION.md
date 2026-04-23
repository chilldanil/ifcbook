# Phase 3A Validation Log

Date: 2026-04-23

## What changed in this step

- Added runtime geometry aggregation to pipeline output:
  - `metadata/geometry_runtime_summary.json`
- Added fallback accounting fields in geometry domain and OCCT extraction report:
  - total fallback events
  - per-class fallback counts
  - timeout / exception / empty fallback counters
- Hardened bundle replay so it always emits `geometry_runtime_summary.json`
  (computed from `view_geometry.json` when the source bundle does not contain it).
- Added opt-in Phase 3B profile:
  - `ifc_book_prototype/profiles/din_iso_arch_floor_plan_v2_phase3b.json`

## Environment notes

- Local runtime has `ifcopenshell` available.
- Local runtime does **not** have `pythonocc-core` available (`OCCT_AVAILABLE=false`).
- Because of that, OCCT-active fallback-rate validation must be run on an OCCT-enabled worker.

## Validation runs

## 1) Test gate

Command:

```bash
LC_ALL=C.UTF-8 TZ=UTC PYTHONHASHSEED=0 pytest tests/ -q -m "not slow"
```

Result:

- `18 passed, 1 skipped, 1 deselected`

## 2) Sample IFC live run

Command:

```bash
python -m ifc_book_prototype samples/demo.ifc --out out/real_phase3a
```

Runtime summary (`out/real_phase3a/metadata/geometry_runtime_summary.json`):

- `view_count`: 5
- `backend_counts`: `ifcopenshell-svg-floorplan: 5`
- `occt_view_count`: 0
- `fallback.events_total`: 0
- `fallback.by_class`: empty

## 3) Large-model path via cached bundle replay

Command:

```bash
python -m ifc_book_prototype --bundle out/demo --out out/demo_phase3a_v2
```

Runtime summary (`out/demo_phase3a_v2/metadata/geometry_runtime_summary.json`):

- `view_count`: 9
- `backend_counts`: `ifcopenshell-svg-floorplan: 9`
- `occt_view_count`: 0
- `fallback.events_total`: 0
- `fallback.by_class`: empty

Interpretation:

- Phase 3A instrumentation is active and producing deterministic runtime summaries.
- OCCT fallback metrics are wired, but currently zero in this environment because OCCT backend is not active locally.

## 4) OCCT-enabled worker procedure

When running on a worker with `pythonocc-core==7.8.1.1` installed, use the following
steps to capture real fallback rates under the configured 2.0 s per-element budget:

```bash
pip install -e '.[ifc,dev,occt]'
LC_ALL=C.UTF-8 TZ=UTC PYTHONHASHSEED=0 \
  python -m ifc_book_prototype.cli samples/Building-Architecture.ifc --out out/occt_small
LC_ALL=C.UTF-8 TZ=UTC PYTHONHASHSEED=0 \
  python -m ifc_book_prototype.cli samples/Hochvolthaus.ifc --out out/occt_large

python -m ifc_book_prototype.cli --summarize-runtime out/occt_small
python -m ifc_book_prototype.cli --summarize-runtime out/occt_large
```

The `--summarize-runtime` subcommand extracts per-run counters from
`metadata/geometry_runtime_summary.json` without re-executing the pipeline.

Acceptance checks to capture per sample in follow-up commits:

- `occt_view_count` is greater than zero on the composite backend.
- `fallback.timeout_events` should be a small fraction of `CUT` linework count on
  small samples; on large samples it is expected to be nonzero — the metric we
  want to tune `occt_per_element_budget_s` against.
- Two back-to-back runs produce byte-identical `book.pdf` and sheet SVGs
  (re-run the determinism gate to confirm).
