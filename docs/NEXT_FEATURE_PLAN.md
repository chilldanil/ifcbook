# Next Feature Plan

Snapshot date: 2026-05-13

This plan translates the current implementation state into the next features worth building. It is intentionally execution-oriented: each phase should either reduce geometry risk, make iteration cheaper, or move the output closer to production drawing books.

## Where We Are Now

- The pipeline is real end-to-end: preflight -> normalization -> view planning -> geometry -> schedules -> SVG sheets -> PDF -> manifests.
- Determinism checks exist for `book.pdf`, sheet SVGs, and normalized `manifest.json`.
- Geometry is hybrid:
  - OCCT cut extraction for configured `cut_classes` when `[occt]` is installed.
  - Owned projected/hidden linework is available behind profile toggles.
  - Serializer and mesh paths remain as safety fallbacks.
- The typed line model is live in rendering (`LineKind`, `LineweightClass`, `TypedLine2D`, `ViewLinework`).
- Feature overlays are real enough for an MVP: door symbols, stair arrows, room tags, profile toggles, leader lines, and collision offsets.
- Stage artifact groundwork exists: `metadata/view_linework.json`, `stage_artifacts`, cache keys, and bundle replay already preserve typed linework metadata.

## Next Features

### Phase 4A: Stage Replay Rerender From Typed Linework

Priority: highest.

This is the next feature to build because it separates expensive geometry extraction from cheap drawing iteration. Today bundle replay mostly copies existing SVG sheets. The next step is to regenerate view sheets and `book.pdf` from cached typed linework without reopening the IFC.

Scope:

- Add a replay path that consumes:
  - `metadata/view_linework.json`
  - `metadata/view_manifest.json`
  - `metadata/normalized_model.json`
  - `metadata/schedule_manifest.json`
  - a selected style profile
- Rebuild view SVGs from cached typed linework.
- Rebuild `book.pdf` from regenerated SVGs.
- Preserve current bundle-copy replay as the legacy/fast path.
- Emit clear replay metadata showing whether a bundle used copied SVGs or rerendered typed linework.

Acceptance criteria:

- A cached bundle can change lineweights, colors, title block text, and overlay/profile rules without reopening the IFC.
- Replay output is deterministic across repeated runs.
- Legacy bundles without `view_linework.json` still degrade to copy-based replay.
- `manifest.json` exposes enough cache/replay metadata to make CI and worker behavior inspectable.

Why this comes first:

- It reduces iteration time for every later drawing/style feature.
- It creates a practical boundary between geometry workers and sheet/book workers.
- It turns the existing `view_linework.json` artifact into an actual product capability instead of passive metadata.

### Phase 4B: Hidden-Line Quality Hardening

Priority: high.

Owned hidden extraction exists, but it is still early-quality. The next geometry work should measure and tune it on large models instead of adding another broad geometry feature blindly.

Scope:

- Run the Phase 3C hidden profile on larger OCCT-enabled models.
- Measure false positives, false negatives, timeout behavior, and hidden-line density.
- Calibrate HLR extraction and de-duplication thresholds.
- Add class-by-class visual regression fixtures for owned projected/hidden output.
- Tighten runtime gates only after the measured baseline is credible.

Acceptance criteria:

- `hidden_line_ratio` becomes useful as a quality signal, not just a count.
- Hidden-line output does not create visible clutter on baseline samples.
- Runtime gates can fail noisy or empty hidden extraction in CI/worker validation.
- Visual fixtures cover at least walls, slabs, columns/beams/members, and one mixed professional sample.

Current status:

- Owned projection is implemented behind `floor_plan.own_projection`.
- View-band clipping is active for owned projected/hidden extraction.
- Best-effort HLR hidden extraction is wired behind `floor_plan.own_hidden`.
- Orientation-agnostic owned line de-duplication is already implemented; the remaining work is validation and tuning, not first implementation.

### Phase 4C: Semantic Drafting Upgrades

Priority: medium-high.

This is the next user-visible quality jump after replay and hidden-line hardening. The current symbols are deterministic, but several semantics are still heuristic or only partially IFC-backed.

Scope:

- Expand door swing handedness beyond `IfcDoor.OperationType` / `UserDefinedOperationType`.
- Improve stair direction using richer stair-path semantics where available.
- Use IFC space names/numbers for room tags through a profile-controlled label policy.
- Keep deterministic fallback behavior for models with weak or missing semantics.

Acceptance criteria:

- Room tags can use real IFC names/numbers when present.
- Door/stair annotations remain stable under reruns.
- Profile options make the annotation source explicit: sequential, numeric, IFC name, IFC long name, or fixed label.
- Bundle replay and typed-linework rerender use the same annotation policy.

### Phase 5: Production Cache And Worker Readiness

Priority: medium.

This phase should start after typed-linework rerender proves the stage boundary. It is the bridge from local prototype to SaaS/worker runtime.

Scope:

- Formalize cache keys per stage: IFC scan, normalized model, geometry linework, sheets, PDF/book.
- Add structured per-stage logs with view/storey correlation.
- Make failed stages retryable without rerunning completed stages.
- Add worker-safe validation commands that use the same determinism and runtime gates as local runs.

Acceptance criteria:

- A geometry-complete bundle can regenerate sheets and PDF without IFC access.
- A sheet/style failure can be retried without rerunning geometry.
- Runtime summaries, gate results, and replay metadata are machine-readable enough for CI dashboards and worker orchestration.

## Immediate Implementation Start

1. Implement typed-linework rerender replay:
   - Add a CLI flag or replay mode that regenerates sheets from `metadata/view_linework.json`.
   - Reuse existing render paths where possible instead of creating a separate renderer dialect.
   - Keep copy-based bundle replay as fallback for legacy bundles.

2. Add focused tests for replay behavior:
   - Cached typed linework rerenders deterministic SVG/PDF outputs.
   - Missing typed linework falls back to existing copy replay.
   - Profile lineweight/color changes affect rerendered sheets without reopening IFC.

3. Validate hidden-line quality on OCCT-enabled samples:
   - Run the hidden profile across multiple models.
   - Capture benchmark summaries, runtime gates, and visual snapshots.
   - Tune de-dup/HLR only against measured failures.

4. Start the next semantic drafting slice:
   - Room labels from IFC names/numbers are the best first target because they are visible, low-risk, and profile-friendly.
