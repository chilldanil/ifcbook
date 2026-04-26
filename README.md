# IFC Book Prototype

This is a runnable prototype scaffold for the MVP slice defined in the research report:

Current implementation snapshot and roadmap: [PROJECT_STATUS.md](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/PROJECT_STATUS.md)
Next implementation phases: [NEXT_FEATURE_PLAN.md](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/NEXT_FEATURE_PLAN.md)
Phase 3A validation record: [PHASE3A_VALIDATION.md](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/PHASE3A_VALIDATION.md)

- IFC ingest
- preflight and normalization
- view planning for floor plans
- deterministic SVG sheet generation
- deterministic PDF book generation
- manifest and cache-key emission

It is deliberately narrow. The geometry core is still behind a replaceable interface so the next iteration can push further toward exact OCCT section extraction without reworking the rest of the pipeline.

## What It Does Today

- scans IFC SPF text with a stdlib parser,
- optionally enriches metadata with `ifcopenshell` when installed,
- builds a canonical job manifest,
- creates cover, index, and per-storey prototype sheets,
- emits:
  - `manifest.json`
  - `preflight.json`
  - `normalized_model.json`
  - `view_manifest.json`
  - `book.pdf`
  - `sheets/*.svg`

The current sheet renderer now places real storey linework from `IfcOpenShell`'s floorplan SVG serializer when available. It is still not publication-grade drafting, but it is no longer a fake visualization.

## Quick Start

Run against a local IFC:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install ifcopenshell
python -m ifc_book_prototype path/to/model.ifc --out out/demo
```

Or call the CLI directly:

```bash
python -m ifc_book_prototype.cli path/to/model.ifc --out out/job-001
```

Summarize runtime counters from an existing run:

```bash
python -m ifc_book_prototype.cli --summarize-runtime out/job-001
```

Run the acceptance gate (returns non-zero on violations):

```bash
python -m ifc_book_prototype.cli \
  --runtime-gate out/job-001 \
  --max-fallback-event-rate 0.20 \
  --max-timeout-events-total 0 \
  --min-occt-coverage-rate 0.50 \
  --min-hidden-lines-total 100 \
  --min-hidden-line-ratio 0.05
```

Machine-readable output is emitted as `RUNTIME_GATE_JSON=<json>` for CI parsing, including hidden-line metrics (`hidden_lines_total`, `hidden_line_ratio`).

Run multi-sample OCCT validation + benchmark summary:

```bash
bash scripts/run_occt_validation.sh
```

This writes:

- `out/occt_validation/<sample>/metadata/benchmark_runtime.json`
- `out/occt_validation/<sample>/metadata/runtime_gate_result.json`
- `out/occt_validation/benchmark_summary.json`
- `out/occt_validation/benchmark_summary.md`
- `out/occt_validation/next_steps.md`
- `out/occt_validation/next_steps.json`
- `out/occt_validation/next_steps.svg`

`benchmark_summary.{json,md}` now also includes hidden-line progress metrics (`hidden_lines_total`, `hidden_line_ratio`) in aggregate and per-sample sections.

Generate an actionable next-step plan from existing run artifacts:

```bash
python -m ifc_book_prototype.cli \
  --plan-next out/occt_validation \
  --plan-next-out out/occt_validation/next_steps.md \
  --plan-next-json-out out/occt_validation/next_steps.json \
  --plan-next-svg-out out/occt_validation/next_steps.svg
```

This prints aggregate medians and a deterministic numbered recommendation list, and can emit markdown/JSON/SVG planning artifacts for CI dashboards.

You can also aggregate any existing run root directly:

```bash
python -m ifc_book_prototype.benchmark out/occt_validation --strict-gate
```

Optional env overrides:

```bash
MAX_FALLBACK_EVENT_RATE=0.20 \
MAX_TIMEOUT_EVENTS_TOTAL=0 \
MIN_OCCT_COVERAGE_RATE=0.50 \
MIN_HIDDEN_LINES_TOTAL=100 \
MIN_HIDDEN_LINE_RATIO=0.05 \
PROFILE_PATH=ifc_book_prototype/profiles/din_iso_arch_floor_plan_v3_phase3c_owned_projection.json \
bash scripts/run_occt_validation.sh
```

For a simple desktop UI (file pickers + run log + quick open of output folder/PDF):

```bash
python -m ifc_book_prototype.ui
```

Or, after editable/package install:

```bash
ifc-book-prototype-ui
```

The UI supports both IFC mode and bundle replay mode, and it invokes the same pipeline path as the CLI.
It also includes post-run controls for runtime-gate evaluation and benchmark-summary generation (without leaving the desktop app).

For large professional models where you already have a generated artifact bundle, replay the bundle without reopening the IFC:

```bash
python -m ifc_book_prototype --bundle out/demo --out out/demo_replayed
```

If `ifcopenshell` is available, the prototype will use it for metadata enrichment and real floor-plan extraction. Otherwise it falls back to SPF scanning only.

The `samples/` directory is intended for local test IFCs and is gitignored by default.

To run the opt-in Phase 3B cut-class expansion profile (adds `IfcColumn`, `IfcBeam`, `IfcMember` to `cut_classes`):

```bash
python -m ifc_book_prototype path/to/model.ifc --out out/job-001 --profile ifc_book_prototype/profiles/din_iso_arch_floor_plan_v2_phase3b.json
```

To run the opt-in Phase 3C owned projection profile (suppresses serializer projection and uses owned projected line extraction when OCCT is available):

```bash
python -m ifc_book_prototype path/to/model.ifc --out out/job-001 --profile ifc_book_prototype/profiles/din_iso_arch_floor_plan_v3_phase3c_owned_projection.json
```

To run the opt-in Phase 3C owned projection + hidden profile:

```bash
python -m ifc_book_prototype path/to/model.ifc --out out/job-001 --profile ifc_book_prototype/profiles/din_iso_arch_floor_plan_v3_phase3c_owned_projection_hidden.json
```

To see profile-driven annotation behavior (doors disabled, fixed room label `SPACE`):

```bash
python -m ifc_book_prototype path/to/model.ifc --out out/job-001 --profile ifc_book_prototype/profiles/din_iso_arch_floor_plan_v1_office_overlay_demo.json
```

## Prototype Scope

Current implementation:

- deterministic pipeline orchestration,
- style-profile loading,
- IFC preflight,
- normalized model summary,
- view planning,
- real per-storey linework extraction through `IfcOpenShell`'s floorplan SVG serializer when available,
- mesh-footprint fallback when serializer extraction fails on a model,
- capability-driven schedule planning that activates only for IFC content that is actually present,
- deterministic feature overlays on view sheets (`D` door symbols with swing arcs, `UP` stair arrows, `R-###` room tags) when geometry anchors are available,
- IFC-semantic feature anchor extraction (door/stair/space placements by storey) now feeds the renderer directly, so overlays are no longer dependent on serializer class-path luck,
- feature-overlay behavior is style-profile driven (`floor_plan.feature_overlay`): per-feature enable/disable, symbol limits, colors, leader behavior, and room-label policy (`sequential` / `numeric` / `fixed` / `ifc_name`),
- SVG-first sheet generation with PDF assembled from the generated sheet SVGs,
- per-view geometry metadata export.

Bundle replay mode:

- copies the cached sheet SVGs from a prior run,
- writes a fresh `manifest.json` with new absolute output paths,
- emits `metadata/bundle_summary.json` so large-model bundles can be inspected without reopening the IFC,
- emits `metadata/geometry_runtime_summary.json` with backend usage and fallback counters,
- injects replay feature overlays for doors/stairs/rooms on copied view sheets using cached model capability counts and profile feature toggles/colors,
- when cached `view_geometry.json` contains serialized `feature_anchors`, replay can also place door/stair/room symbols without reopening the IFC,
- rebuilds `book.pdf` from the cached sheet SVGs so the PDF follows the canonical sheet artifacts instead of a separate placeholder path.

Not implemented yet:

- full-class exact section cutting (current OCCT cut path is partial and profile-scoped),
- projected visible-line extraction,
- hidden-line suppression rules,
- room polygon derivation,
- automated dimensions,
- IFC-backed annotation persistence.

Schedule behavior is intentionally generic rather than sample-specific:

- spaces create a space schedule when `IfcSpace` is present,
- doors and windows create an opening type schedule when `IfcDoor` / `IfcWindow` are present,
- stairs and ramps create a circulation schedule when `IfcStair` / `IfcRamp` are present,
- structural elements create a type schedule when `IfcColumn` / `IfcBeam` / `IfcMember` / `IfcSlab` are present.

That keeps the planner valid for richer professional models instead of baking assumptions from the included sample IFC into the pipeline.

## Output Layout

```text
out/demo/
  book.pdf
  manifest.json
  metadata/
    preflight.json
    normalized_model.json
    view_manifest.json
    view_geometry.json
    geometry_runtime_summary.json
  sheets/
    A-000_cover.svg
    A-001_index.svg
    A-101_ground_floor.svg
    A-102_first_floor.svg
```

## Next Geometry Step

Refine the real backend in [geometry_backend.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/geometry_backend.py):

1. Exact OCCT/BRep section extraction for cut geometry instead of relying on IfcOpenShell's serialized floorplan output.
2. Controlled synthesis for door swings, stair arrows, room tags, and dimensions.
3. Style-profile driven lineweight, hatch, and annotation rules.
4. Rule-driven schedules and sheet-set layout.
