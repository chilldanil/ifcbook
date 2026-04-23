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
- Regression tests added for indexing determinism and fallback reporting.

### Phase 3B: Expand OCCT Cut Coverage

Scope:

- Extend `cut_classes` default profile coverage to: `IfcColumn`, `IfcBeam`, `IfcMember` (after validation).
- Keep profile override so customers can scope classes by style/profile.
- Add class-level visual regression fixtures for new cut classes.

Acceptance criteria:

- Deterministic output remains byte-identical across reruns.
- `linework_counts` shows increased `CUT` coverage on professional models.
- No reduction in total drawing completeness vs current serializer-first output.

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
