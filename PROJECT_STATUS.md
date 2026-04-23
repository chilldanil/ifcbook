# Project Status

Snapshot date: 2026-04-23

This note marks the current implementation state of the IFC-to-drawing-book prototype, what already exists in the repo, and what the next execution targets should be.
Phase 3A measured validation details are tracked in [PHASE3A_VALIDATION.md](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/PHASE3A_VALIDATION.md).

## Where We Are Now

The project is past the research-only phase and into a working prototype phase.

What is real today:

- a runnable CLI pipeline that accepts an IFC or replays an existing generated bundle,
- deterministic preflight, normalization, view planning, schedule planning, sheet generation, and manifest emission,
- real floor-plan linework extraction through `IfcOpenShell`'s floorplan SVG serializer,
- **cut geometry for the configured `cut_classes` (default `IfcWall`, `IfcSlab`) derived from exact OCCT BRep sectioning, with per-element mesh-slice fallback under a configurable wall-clock budget — activated automatically when the `[occt]` extra is installed,**
- **typed line model (`TypedLine2D` / `ViewLinework`) wired through the renderer, with explicit `LineKind` (CUT/PROJECTED/HIDDEN/OUTLINE) and `LineweightClass` (HEAVY/MEDIUM/LIGHT/FINE) classification driving stroke colors and lineweight from the style profile,**
- **shared deterministic storey/elevation indexing helpers are now used across OCCT, serializer, and mesh geometry backends, reducing cross-backend ordering drift risk,**
- **OCCT fallback behavior is now explicit in geometry metadata (`fallback_events`, `fallback_by_class`, timeout/exception counters) and the mesh-slice fallback produces real cut segments at the view cut plane,**
- **`metadata/geometry_runtime_summary.json` now aggregates per-run backend usage, linework totals, and fallback rates for Phase 3A validation,**
- **feature overlays now render deterministic door/stair/room symbols on view sheets (`D` markers with swing arcs, `UP` arrows, `R-###` room tags), with collision-avoidance offsets + leader lines and nearest-wall door alignment; IFC-semantic feature anchors (door/stair/space placement by storey) are now extracted directly and used as primary symbol anchors; overlay toggles/colors/label policy are loaded from `floor_plan.feature_overlay`; bundle replay overlays use the same profile policy and can consume serialized feature anchors,**
- **byte-identical determinism CI gate over `book.pdf`, every sheet SVG, and `manifest.json` (modulo absolute output paths), running on all bundled samples via GitHub Actions,**
- SVG-first sheet generation with `book.pdf` assembled from the generated sheet SVGs,
- capability-driven schedule generation for openings, circulation, spaces, and structural element types,
- bundle replay for large professional models so cached sheet bundles can be repackaged without reopening the IFC.

What is still prototype-grade:

- beyond-cut projection and hidden-line behavior still depend on `IfcOpenShell` serializer output instead of our own geometry kernel,
- the OCCT cut backend ships first for `IfcWall` + `IfcSlab`; extending to columns, beams, doors, windows, and stairs is a one-line edit to `cut_classes` in the style profile but has not been visually validated yet,
- annotations are limited to what can be inferred cheaply from IFC structure and current sheet logic,
- semantic annotation placement is deterministic and now anchored on IFC placements, but still heuristic in parts (door handedness, stair run direction, and room label source policy still need refinement),
- there is no exact dimension engine, room-tag engine, or office-standard drafting ruleset yet.

## What We Have Now

### Core Pipeline

Implemented in:

- [ifc_book_prototype/pipeline.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/pipeline.py)
- [ifc_book_prototype/cli.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/cli.py)
- [ifc_book_prototype/ifc_loader.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/ifc_loader.py)
- [ifc_book_prototype/domain.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/domain.py)

Current pipeline stages:

1. IFC preflight and metadata scan.
2. Model normalization and storey extraction.
3. View planning for floor plans.
4. Geometry extraction.
5. Schedule extraction.
6. Sheet SVG generation.
7. PDF assembly from the generated SVG sheets.
8. Manifest and metadata emission.

### Geometry

Implemented in:

- [ifc_book_prototype/geometry_backend.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/geometry_backend.py)
- [ifc_book_prototype/geometry_occt.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/geometry_occt.py)
- [ifc_book_prototype/occt_section.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/occt_section.py)
- [ifc_book_prototype/_ifc_index.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/_ifc_index.py)

Current state:

- preferred backend: `CompositeGeometryBackend` — OCCT BRep section for cut linework on `cut_classes` (default `IfcWall`, `IfcSlab`) plus the serializer for projection. OCCT runs single-threaded with quantized 1e-5 m output and per-element wall-clock budget (default 2.0 s, profile-driven).
- secondary backend: `IfcSerializerPlanBackend` (`ifcopenshell.draw`).
- tertiary backend: mesh-footprint approximation.
- output: deterministic vector paths, typed `ViewLinework`, and metadata per planned view.

The OCCT layer is dormant when `pythonocc-core` is not installed: the existing serializer + mesh backends remain the active fallback ladder, so the determinism gate is green either way. Goal 1's remaining work is owning projection and hidden-line generation too.

### Sheet Rendering

Implemented in:

- [ifc_book_prototype/render_svg.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/render_svg.py)
- [ifc_book_prototype/render_pdf.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/render_pdf.py)

Current state:

- SVG is the canonical page representation,
- PDF is now assembled from those SVG sheets, not from a separate placeholder PDF path,
- current SVG-to-PDF support covers the SVG subset generated by this prototype: `rect`, `line`, `path`, `text`, and `M/L/H/V/Z` path commands.

### Schedule Planning

Implemented in:

- [ifc_book_prototype/schedules.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/schedules.py)

Current schedule families:

- space schedule when `IfcSpace` exists,
- opening type schedule when `IfcDoor` / `IfcWindow` exist,
- circulation schedule when `IfcStair` / `IfcRamp` exist,
- element type schedule when `IfcColumn` / `IfcBeam` / `IfcMember` / `IfcSlab` exist.

This is intentionally capability-driven, so richer professional IFCs activate more output without changing core code paths.

### Large-Model Bundle Replay

Implemented in:

- [ifc_book_prototype/bundle_replay.py](/Users/daniilchilochi/Downloads/ifc_to_blueprint/ifc%20blue/ifc_book_prototype/bundle_replay.py)

Current state:

- an existing artifact bundle can be replayed with `--bundle`,
- cached sheet SVGs are copied forward,
- `book.pdf` is rebuilt from those cached sheet SVGs,
- `manifest.json` is rewritten for the new output directory,
- `metadata/bundle_summary.json` captures bundle capabilities without re-opening the IFC.

This is the current answer to large professional models that are expensive to reopen during iteration.

## Known Boundaries

These are the main implementation limits right now:

- exact BRep sectioning is currently limited to `cut_classes` (default `IfcWall`, `IfcSlab`) and does not yet cover all major architectural/structural classes,
- no owned projected-line and hidden-line pipeline yet (projection still comes from serializer output),
- OCCT timeout fallback is now functional and observable, but still needs high-volume validation on larger model corpora,
- no hatch generation,
- room tags currently use deterministic sequential IDs (`R-###`) instead of IFC room naming policy,
- no automatic dimensions,
- collision-aware placement is implemented for current feature symbols, but there is no global annotation layout engine yet,
- no full office-standard profile system yet beyond sheet/lineweight plus first overlay controls (`floor_plan.feature_overlay`),
- no worker queue, cache service, or multi-tenant SaaS runtime yet.

## Future Goals

### Goal 1: Replace Serializer-Dependent Geometry

Priority: highest

Target:

- exact OCCT/BRep section extraction for cut geometry,
- controlled projected-line extraction for beyond geometry,
- deterministic curve cleanup, chaining, and de-duplication,
- explicit cut/projected/hidden classification under our control.

This is the main technical gating item for publication-grade output.

### Goal 2: Add Drawing Synthesis

Target:

- door swings,
- stair direction arrows,
- section and elevation markers,
- room tags,
- hatch conventions,
- lineweight hierarchy driven by style profile,
- annotation rules based on IFC semantics plus configurable drafting standards.

### Goal 3: Add Automated Annotation Layout

Target:

- rule-driven dimension chains,
- label anchor selection,
- collision avoidance,
- sheet-space overflow handling,
- deterministic placement order.

### Goal 4: Expand Style Profiles

Target:

- regional conventions,
- office-standard lineweights,
- hatches,
- title block rules,
- schedule formatting,
- annotation symbology,
- no hardcoded drawing conventions in renderers.

### Goal 5: Harden Large-Model Operation

Target:

- stable cached geometry bundles,
- content-addressed artifact caches,
- stage-level replay,
- partial regeneration,
- better metadata summaries for large models,
- clear separation between expensive geometry stages and cheap sheet/book assembly stages.

### Goal 6: Move Toward SaaS Runtime

Target:

- queue and worker model,
- stateless execution boundaries,
- object-store artifact model,
- deterministic version pinning,
- structured logging with view and element correlation,
- memory/time limits per stage.

## Recommended Next Steps

Recommended execution order from here:

1. Validate the hardened OCCT cut path on larger models and profile fallback rates by class under realistic time budgets.
2. Expand OCCT cut coverage beyond `IfcWall` / `IfcSlab` (next target: `IfcColumn`, `IfcBeam`, `IfcMember`) with visual + determinism regression checks.
3. Start owning projected and hidden line generation in the typed line model instead of relying on serializer classification.
4. Move current annotation primitives from heuristic defaults to IFC-semantic rules (door handedness, stair run direction, room label source) with profile-controlled toggles.
5. Expand style profiles from page/lineweights into drafting-rule profiles, then add bundle-level cache keys and per-stage replay metadata for expensive models.

## Practical Status Summary

If someone asks "what do we actually have right now?", the answer is:

- a real end-to-end prototype,
- real vector plan sheets,
- real PDF books assembled from those sheets,
- generic schedule planning,
- large-model bundle replay,
- deterministic outputs,
- but not yet a publication-grade geometry and annotation engine.
