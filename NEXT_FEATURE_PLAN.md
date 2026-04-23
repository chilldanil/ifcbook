# Next Feature Plan

Snapshot date: 2026-04-23

This plan translates the current implementation state into execution phases for the next features.

## Where We Are Now

- The pipeline is real end-to-end: preflight -> normalization -> view planning -> geometry -> schedules -> SVG sheets -> PDF -> manifests.
- Determinism gate exists in CI for `book.pdf`, every sheet SVG, and normalized `manifest.json`.
- Geometry is now hybrid:
  - OCCT cut extraction for configured `cut_classes` (default `IfcWall`, `IfcSlab`) when `[occt]` is installed.
  - Serializer projection + legacy path fallback remain active.
- Typed line model is live in rendering (`LineKind`, `LineweightClass`, `TypedLine2D`, `ViewLinework`).

## Next Features (Execution Order)

### Phase 3A: Geometry Reliability Hardening

Scope:

- Consolidate storey/elevation indexing across all geometry backends through shared helpers.
- Harden OCCT timeout fallback behavior for large/complex elements.
- Add explicit metadata for fallback usage per view and per class.

Acceptance criteria:

- No regressions in determinism gate (`pytest -m "not slow"`).
- Fallback events are visible in `view_geometry.json` linework metadata.
- Large-model run completes without crashing when selected elements exceed OCCT budget.

Current sprint status:

- In progress and partially completed in this branch.
- Shared indexing helpers are wired into serializer and mesh backends.
- OCCT fallback now returns real mesh-slice cut segments at the cut plane.
- Fallback metadata is tracked and emitted (`fallback_events`, `fallback_by_class`, timeout/exception/empty counters).
- Per-run aggregation is emitted in `metadata/geometry_runtime_summary.json`.
- Regression tests added for indexing determinism and fallback reporting.
- Local runtime note: OCCT is currently unavailable in this environment, so OCCT-active fallback-rate measurement must run on an OCCT-enabled worker.

### Phase 3B: Expand OCCT Cut Coverage

Scope:

- Extend `cut_classes` default profile coverage to: `IfcColumn`, `IfcBeam`, `IfcMember` (after validation).
- Keep profile override so customers can scope classes by style/profile.
- Add class-level visual regression fixtures for new cut classes.

Acceptance criteria:

- Deterministic output remains byte-identical across reruns.
- `linework_counts` shows increased `CUT` coverage on professional models.
- No reduction in total drawing completeness vs current serializer-first output.

Current sprint status:

- Phase 3B preview profile is added as opt-in:
  `ifc_book_prototype/profiles/din_iso_arch_floor_plan_v2_phase3b.json`

### Phase 3C: Own Projection + Hidden Lines

Scope:

- Implement typed projected-line generation independent of serializer grouping.
- Add first hidden-line policy in typed output (style-profile controlled).
- Keep serializer as safety fallback, not primary logic.

Acceptance criteria:

- `PROJECTED` and `HIDDEN` lines are produced by internal geometry stage for OCCT-covered classes.
- Renderer lineweights are profile-driven only (no hardcoded drafting semantics).
- Determinism gate remains green.

### Phase 4: Drawing Synthesis + Annotation MVP

Scope:

- Add deterministic primitives for:
  - door swings,
  - stair direction arrows,
  - room tags (when `IfcSpace` exists).
- Add first collision-avoidance pass for tags and symbol anchors.

Acceptance criteria:

- Feature flags/profile knobs can enable/disable each synthesized primitive.
- No overlapping labels on baseline samples in default profile.
- Output remains deterministic under reruns.

Current sprint status:

- First synthesis/placement slice is implemented and shipped in the renderer:
  - deterministic door symbols (`D` + swing arc), stair arrows (`UP`), and room tags (`R-###`) are rendered from IFC-derived anchors,
  - IFC-semantic feature anchor extraction is active in geometry backends (door/stair/space placements by storey), so symbols can render even when serializer class paths are missing,
  - overlay behavior is now profile-driven (`floor_plan.feature_overlay`): per-feature toggles, symbol limits, colors, leader-line settings, and room label policy,
  - deterministic collision-avoidance offset search is active for all three feature types,
  - displaced symbols render leader lines,
  - door symbols align to nearest wall segment when available,
  - bundle replay injects deterministic overlay counts for doors/stairs/rooms from cached metadata using the same profile rules.
- Remaining Phase 4 work is richer semantics and drafting control:
  - real door swing handedness from opening semantics (not heuristic orientation),
  - stair run direction from path/axis semantics rather than line PCA fallback,
  - room labels from real IFC names/numbers and office profile mapping (currently sequential `R-###` IDs).

### Phase 5: SaaS Runtime Readiness

Scope:

- Introduce queue + worker boundaries.
- Add stage-level replay and cache keys (geometry vs sheets vs book assembly).
- Add structured per-stage logs with view/storey correlation.

Acceptance criteria:

- A failed stage can be retried without rerunning completed stages.
- Cached artifacts can regenerate a final book without reopening IFC.
- Determinism checks are runnable in CI and worker runtime with equivalent results.

## Immediate Implementation Start (Next Sprint)

1. Validate Phase 3A behavior on the large-model path and tune per-element OCCT budgets with measured fallback rates.
2. Begin Phase 3B (`IfcColumn`, `IfcBeam`, `IfcMember`) with visual regression fixtures.
3. Keep determinism gate (`book.pdf` + all SVG + normalized `manifest.json`) green while expanding class coverage.
4. Move Phase 4 from profile-driven overlay controls to IFC-semantic drafting rules (door handedness, stair run direction, room label source mapping).
