# IFC Book Prototype

This is a runnable prototype scaffold for the MVP slice defined in the research report:

Current implementation snapshot and roadmap: [PROJECT_STATUS.md](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/PROJECT_STATUS.md)

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

For large professional models where you already have a generated artifact bundle, replay the bundle without reopening the IFC:

```bash
python -m ifc_book_prototype --bundle out/demo --out out/demo_replayed
```

If `ifcopenshell` is available, the prototype will use it for metadata enrichment and real floor-plan extraction. Otherwise it falls back to SPF scanning only.

The `samples/` directory is intended for local test IFCs and is gitignored by default.

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
- SVG-first sheet generation with PDF assembled from the generated sheet SVGs,
- per-view geometry metadata export.

Bundle replay mode:

- copies the cached sheet SVGs from a prior run,
- writes a fresh `manifest.json` with new absolute output paths,
- emits `metadata/bundle_summary.json` so large-model bundles can be inspected without reopening the IFC,
- rebuilds `book.pdf` from the cached sheet SVGs so the PDF follows the canonical sheet artifacts instead of a separate placeholder path.

Not implemented yet:

- exact section cutting,
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
