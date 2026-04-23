"""Owned projection + hidden line generation (Phase 3C).

This module is the home for *owned* projected and hidden line extraction,
replacing today's serializer-derived PROJECTED paths and the absence of real
HIDDEN linework.

Gated by two profile toggles (both default ``False`` → back-compat):
  - ``floor_plan.own_projection``: emit PROJECTED lines from owned BRep edges.
  - ``floor_plan.own_hidden``: reserved for HLR-driven hidden-line extraction
    (see Roadmap below).

Current implementation (step 1 — "all-edges projection"):

  For each element:
    1. Fetch the BRep shape via the same ``brep_from_ifc_element`` path the
       cut extractor uses.
    2. Iterate every ``TopAbs_EDGE`` of the shape.
    3. Sample each edge to a quantized 2D polyline (XY projection).
    4. Drop degenerate collapses (vertical edges that collapse to a single
       XY point) and edges whose every sample is coplanar with the cut plane
       (those are already emitted by the CUT extractor).
    5. Chain, sort, and wrap as ``TypedLine2D(kind=PROJECTED,
       lineweight_class=LIGHT)``.

Step 1 is deliberately naive: it does not classify visibility. A wall standing
between two rooms will have both of its bounding edges drawn, not the
single "visible" one. The serializer path remains the better default until
the HLR pass lands; this is why the feature is opt-in.

Roadmap (tracked in NEXT_FEATURE_PLAN.md Phase 3C):

  - step 2: view-band clipping via OCCT half-space cut at
    ``storey_elevation - view_depth_below_m`` (bottom) and
    ``storey_elevation + cut_plane_m + overhead_depth_above_m`` (top).
  - step 3: HLR (`HLRBRep_Algo`) pass with projection direction (0,0,-1) to
    separate visible from hidden edges. Hidden edges feed
    ``extract_owned_hidden_lines`` when ``own_hidden=True``.
  - step 4: de-duplication across adjacent elements (two walls sharing an
    edge should emit it once) via content-hash reduction on the quantized
    polyline.

Determinism: the public functions reuse ``quantize_point``, ``chain_polylines``,
and ``typed_line_sort_key`` so output is byte-identical across reruns.
"""
from __future__ import annotations

from typing import Iterable, List, Sequence

from . import occt_section
from .domain import (
    LineKind,
    LineweightClass,
    PlannedView,
    Point2D,
    StyleProfile,
    TypedLine2D,
    typed_line_sort_key,
)


__all__ = [
    "extract_owned_projection_lines",
    "extract_owned_hidden_lines",
    "owned_projection_enabled",
    "owned_hidden_enabled",
]


def owned_projection_enabled(profile: StyleProfile) -> bool:
    return bool(getattr(profile.floor_plan, "own_projection", False))


def owned_hidden_enabled(profile: StyleProfile) -> bool:
    return bool(getattr(profile.floor_plan, "own_hidden", False))


def extract_owned_projection_lines(
    *,
    view: PlannedView,
    profile: StyleProfile,
    elements: Iterable[object],
    ifc_geom_module: object,
    storey_elevation_m: float,
) -> List[TypedLine2D]:
    """Return owned PROJECTED lines for the view.

    Gated by ``floor_plan.own_projection``. When disabled (default) returns
    ``[]`` without touching OCCT. When enabled and OCCT is unavailable,
    returns ``[]`` rather than raising — the composite backend treats this as
    "owned path is a no-op for this run".

    Step 1 implementation (see module docstring): project every BRep edge
    to XY, drop cut-plane-coplanar edges, chain, quantize, sort.
    """
    if not owned_projection_enabled(profile):
        return []
    if not occt_section.OCCT_AVAILABLE:
        return []

    cut_plane_z = storey_elevation_m + view.cut_plane_m
    chord_tol = profile.floor_plan.cut_chord_tolerance_m
    budget_s = profile.floor_plan.occt_per_element_budget_s

    sorted_elements = sorted(
        elements,
        key=lambda el: (el.is_a(), getattr(el, "GlobalId", "") or "", el.id()),
    )

    results: List[TypedLine2D] = []
    for element in sorted_elements:
        ifc_class = element.is_a()
        global_id = getattr(element, "GlobalId", "") or ""
        try:
            polylines = occt_section.run_with_budget(
                lambda el=element: _project_edges_of_element(
                    ifc_geom_module, el, chord_tol, cut_plane_z
                ),
                budget_s,
            )
        except Exception:
            # Owned projection is best-effort for now; a per-element failure
            # must not break the view. The cut extractor already records
            # fallback events; for PROJECTED we simply skip.
            continue
        for polyline in polylines:
            if len(polyline) < 2:
                continue
            results.append(
                TypedLine2D(
                    kind=LineKind.PROJECTED,
                    lineweight_class=LineweightClass.LIGHT,
                    points=[Point2D(x=x, y=y) for (x, y) in polyline],
                    closed=polyline[0] == polyline[-1] and len(polyline) > 2,
                    source_element=global_id,
                    source_ifc_class=ifc_class,
                )
            )

    return sorted(results, key=typed_line_sort_key)


def extract_owned_hidden_lines(
    *,
    view: PlannedView,
    profile: StyleProfile,
    elements: Iterable[object],
    ifc_geom_module: object,
    storey_elevation_m: float,
) -> List[TypedLine2D]:
    """Return owned HIDDEN lines for the view.

    Gated by ``floor_plan.own_hidden``. Real implementation requires the HLR
    pass (Phase 3C step 3); currently returns ``[]`` even when the toggle is
    on, so enabling the toggle is safe but has no effect yet. The contract
    surface is preserved so the composite backend can wire the call today.
    """
    if not owned_hidden_enabled(profile):
        return []
    # HLR (Phase 3C step 3) lands here. Until then, honestly return no lines
    # rather than producing misleading output.
    _ = (view, elements, ifc_geom_module, storey_elevation_m)
    return []


# ---------------------------------------------------------------------------
# OCCT edge projection helpers
# ---------------------------------------------------------------------------


def _project_edges_of_element(ifc_geom_module, element, chord_tol_m, cut_plane_z):
    """Project every edge of an element's BRep to XY.

    Returns a list of 2D polylines suitable for chaining into
    ``TypedLine2D`` objects. Filters out edges coplanar with the cut plane
    (already emitted by the cut extractor) and degenerate vertical edges
    (collapse to a single XY point).
    """
    if not occt_section.OCCT_AVAILABLE:
        return []

    shape = occt_section.brep_from_ifc_element(ifc_geom_module, None, element)
    if shape is None:
        return []

    # Local OCCT import — safe because OCCT_AVAILABLE gates entry here.
    from OCC.Core.TopExp import TopExp_Explorer  # type: ignore
    from OCC.Core.TopAbs import TopAbs_EDGE  # type: ignore

    raw_segments = []
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    while explorer.More():
        edge = explorer.Current()
        polyline = occt_section.edge_to_polyline(edge, chord_tol_m)
        explorer.Next()
        if len(polyline) < 2:
            continue
        # Degenerate XY projection: vertical edges collapse to a point.
        if all(p == polyline[0] for p in polyline):
            continue
        # Drop edges that sit exactly on the cut plane — the cut extractor
        # owns those. Approximate by checking the Z-sample of the BRep edge
        # via its first vertex.
        if _edge_is_on_cut_plane(edge, cut_plane_z):
            continue
        raw_segments.append(polyline)

    raw_segments.sort(key=lambda seg: (seg[0][0], seg[0][1], seg[-1][0], seg[-1][1], len(seg)))
    chains = occt_section.chain_polylines(raw_segments)
    return [chain for chain in chains if len(chain) >= 2]


def _edge_is_on_cut_plane(edge, cut_plane_z: float, tol_m: float = 1.0e-4) -> bool:
    """Return True if the edge's first vertex lies within ``tol_m`` of the cut plane.

    This is a cheap filter — not exact. A slanted edge that merely touches the
    cut plane at its first vertex would be falsely dropped. In practice such
    edges are rare in building geometry; when they occur, losing the projection
    is preferable to duplicating with the cut extractor.
    """
    if not occt_section.OCCT_AVAILABLE:
        return False
    from OCC.Core.BRep import BRep_Tool  # type: ignore
    from OCC.Core.TopExp import TopExp_Explorer  # type: ignore
    from OCC.Core.TopAbs import TopAbs_VERTEX  # type: ignore

    explorer = TopExp_Explorer(edge, TopAbs_VERTEX)
    if not explorer.More():
        return False
    pnt = BRep_Tool.Pnt(explorer.Current())
    return abs(pnt.Z() - cut_plane_z) <= tol_m


def merge_owned_lines_into(
    base_lines: Sequence[TypedLine2D],
    owned_projection: Sequence[TypedLine2D],
    owned_hidden: Sequence[TypedLine2D],
    *,
    suppress_serializer_projection: bool,
) -> List[TypedLine2D]:
    """Compose owned projection + hidden into an existing line list.

    When ``suppress_serializer_projection`` is True, PROJECTED lines from the
    serializer are dropped in favor of the owned lines (even if the owned set
    is empty — "own it or bust"). HIDDEN lines are additive because the
    serializer never produces HIDDEN today.
    """
    from .domain import LineKind  # local import to keep module load cheap

    kept = (
        [line for line in base_lines if line.kind is not LineKind.PROJECTED]
        if suppress_serializer_projection
        else list(base_lines)
    )
    kept.extend(owned_projection)
    kept.extend(owned_hidden)
    return kept
