"""Owned projection + hidden line generation (Phase 3C).

This module is the home for *owned* projected and hidden line extraction,
replacing today's serializer-derived PROJECTED paths and the absence of real
HIDDEN linework.

Gated by two profile toggles (both default ``False`` → back-compat):
  - ``floor_plan.own_projection``: emit PROJECTED lines from owned BRep edges.
  - ``floor_plan.own_hidden``: reserved for HLR-driven hidden-line extraction
    (see Roadmap below).

Current implementation status:

  Projection (steps 1 + 2):
    For each element:
    1. Fetch the BRep shape via the same ``brep_from_ifc_element`` path the
       cut extractor uses.
    2. Iterate every ``TopAbs_EDGE`` of the shape.
    3. Sample each edge to a quantized 3D polyline.
    4. Drop degenerate collapses (vertical edges that collapse to a single
       XY point) and edges whose every sample is coplanar with the cut plane
       (those are already emitted by the CUT extractor).
    5. Clip to the plan view vertical band.
    6. Project to XY, chain, sort, and wrap as ``TypedLine2D(kind=PROJECTED,
       lineweight_class=LIGHT)``.

  Hidden (step 3, best-effort):
    - per-element HLR pass via ``HLRBRep_Algo``;
    - extract hidden compounds from ``HLRBRep_HLRToShape``;
    - sample + band-clip + emit ``TypedLine2D(kind=HIDDEN, lineweight_class=FINE)``.

The path remains opt-in because hidden quality and de-dup need further tuning.

Roadmap (tracked in NEXT_FEATURE_PLAN.md Phase 3C):

  - step 4: de-duplication across adjacent elements (two walls sharing an
    edge should emit it once) via content-hash reduction on the quantized
    polyline.

Determinism: the public functions reuse ``quantize_point``, ``chain_polylines``,
``typed_line_sort_key``, and canonical line de-duplication keys so output is
byte-identical across reruns.
"""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

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
    view_band_low_z = storey_elevation_m - view.view_depth_below_m
    view_band_high_z = storey_elevation_m + view.cut_plane_m + view.overhead_depth_above_m
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
                    ifc_geom_module,
                    el,
                    chord_tol,
                    cut_plane_z,
                    view_band_low_z,
                    view_band_high_z,
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

    return _deduplicate_typed_lines(sorted(results, key=typed_line_sort_key))


def extract_owned_hidden_lines(
    *,
    view: PlannedView,
    profile: StyleProfile,
    elements: Iterable[object],
    ifc_geom_module: object,
    storey_elevation_m: float,
) -> List[TypedLine2D]:
    """Return owned HIDDEN lines for the view.

    Gated by ``floor_plan.own_hidden``. This is a best-effort HLR path:
    when OCCT/HLR bindings are unavailable or an element fails, that element
    contributes no hidden output but the run continues.
    """
    if not owned_hidden_enabled(profile):
        return []
    if not occt_section.OCCT_AVAILABLE:
        return []

    view_band_low_z = storey_elevation_m - view.view_depth_below_m
    view_band_high_z = storey_elevation_m + view.cut_plane_m + view.overhead_depth_above_m
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
                lambda el=element: _hidden_edges_of_element(
                    ifc_geom_module=ifc_geom_module,
                    element=el,
                    chord_tol_m=chord_tol,
                    view_band_low_z=view_band_low_z,
                    view_band_high_z=view_band_high_z,
                ),
                budget_s,
            )
        except Exception:
            continue
        for polyline in polylines:
            if len(polyline) < 2:
                continue
            results.append(
                TypedLine2D(
                    kind=LineKind.HIDDEN,
                    lineweight_class=LineweightClass.FINE,
                    points=[Point2D(x=x, y=y) for (x, y) in polyline],
                    closed=polyline[0] == polyline[-1] and len(polyline) > 2,
                    source_element=global_id,
                    source_ifc_class=ifc_class,
                )
            )
    return _deduplicate_typed_lines(sorted(results, key=typed_line_sort_key))


# ---------------------------------------------------------------------------
# OCCT edge projection helpers
# ---------------------------------------------------------------------------


def _project_edges_of_element(
    ifc_geom_module,
    element,
    chord_tol_m: float,
    cut_plane_z: float,
    view_band_low_z: float,
    view_band_high_z: float,
):
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
        polyline_3d = occt_section.edge_to_polyline_3d(edge, chord_tol_m)
        explorer.Next()
        if len(polyline_3d) < 2:
            continue
        # Drop edges that sit exactly on the cut plane — the cut extractor
        # owns those. Approximate by checking the Z-sample of the BRep edge
        # via its first vertex.
        if _edge_is_on_cut_plane(edge, cut_plane_z):
            continue
        clipped = _clip_polyline_3d_to_z_band(
            polyline_3d=polyline_3d,
            z_low=view_band_low_z,
            z_high=view_band_high_z,
        )
        raw_segments.extend(clipped)

    raw_segments.sort(key=lambda seg: (seg[0][0], seg[0][1], seg[-1][0], seg[-1][1], len(seg)))
    chains = occt_section.chain_polylines(raw_segments)
    return [chain for chain in chains if len(chain) >= 2]


def _hidden_edges_of_element(
    *,
    ifc_geom_module,
    element,
    chord_tol_m: float,
    view_band_low_z: float,
    view_band_high_z: float,
) -> List[List[Tuple[float, float]]]:
    if not occt_section.OCCT_AVAILABLE:
        return []

    shape = occt_section.brep_from_ifc_element(ifc_geom_module, None, element)
    if shape is None:
        return []

    imports = _import_hlr_primitives()
    if imports is None:
        return []
    HLRBRep_Algo, HLRBRep_HLRToShape, HLRAlgo_Projector, gp_Ax2, gp_Pnt, gp_Dir, TopExp_Explorer, TopAbs_EDGE = imports

    algo = HLRBRep_Algo()
    algo.Add(shape)
    projector = HLRAlgo_Projector(gp_Ax2(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0)))
    algo.Projector(projector)
    algo.Update()
    algo.Hide()

    hlr_shape = HLRBRep_HLRToShape(algo)
    hidden_compounds = _collect_hlr_hidden_compounds(hlr_shape)
    if not hidden_compounds:
        return []

    raw_segments: List[List[Tuple[float, float]]] = []
    for hidden_compound in hidden_compounds:
        try:
            explorer = TopExp_Explorer(hidden_compound, TopAbs_EDGE)
        except Exception:
            continue
        while True:
            try:
                more = explorer.More()
            except Exception:
                break
            if not more:
                break
            try:
                edge = explorer.Current()
            except Exception:
                try:
                    explorer.Next()
                except Exception:
                    pass
                continue
            try:
                polyline_3d = occt_section.edge_to_polyline_3d(edge, chord_tol_m)
            except Exception:
                polyline_3d = []
            try:
                explorer.Next()
            except Exception:
                break
            if len(polyline_3d) < 2:
                continue
            clipped = _clip_polyline_3d_to_z_band(
                polyline_3d=polyline_3d,
                z_low=view_band_low_z,
                z_high=view_band_high_z,
            )
            if clipped:
                raw_segments.extend(clipped)
                continue
            # Some IfcOpenShell/pythonocc combinations expose HLR edges in
            # projector coordinates (z ~= 0) rather than model coordinates.
            # In that mode model-space Z clipping drops every hidden edge.
            if _looks_like_projected_hlr_polyline(polyline_3d):
                raw_segments.extend(_polyline_3d_to_2d_segments(polyline_3d))

    deduped_segments = _deduplicate_2d_polylines(raw_segments)
    chains = occt_section.chain_polylines(deduped_segments)
    filtered_chains = [chain for chain in chains if len(chain) >= 2]
    return _deduplicate_2d_polylines(filtered_chains)


def _import_hlr_primitives():
    try:
        from OCC.Core.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape  # type: ignore
        from OCC.Core.HLRAlgo import HLRAlgo_Projector  # type: ignore
        from OCC.Core.gp import gp_Ax2, gp_Pnt, gp_Dir  # type: ignore
        from OCC.Core.TopExp import TopExp_Explorer  # type: ignore
        from OCC.Core.TopAbs import TopAbs_EDGE  # type: ignore
    except Exception:
        return None
    return (
        HLRBRep_Algo,
        HLRBRep_HLRToShape,
        HLRAlgo_Projector,
        gp_Ax2,
        gp_Pnt,
        gp_Dir,
        TopExp_Explorer,
        TopAbs_EDGE,
    )


def _collect_hlr_hidden_compounds(hlr_shape) -> List[object]:
    # Different pythonocc versions expose different subsets of compounds.
    compounds: List[object] = []
    for getter_name in (
        "HCompound",          # hidden edges
        "OutLineHCompound",   # hidden outlines (if exposed)
        "Rg1LineHCompound",   # hidden smooth edges
        "RgNLineHCompound",   # hidden sharp edges
        "IsoLineHCompound",   # hidden iso-lines (if exposed)
    ):
        if not hasattr(hlr_shape, getter_name):
            continue
        try:
            compound = getattr(hlr_shape, getter_name)()
        except Exception:
            continue
        if compound is None:
            continue
        try:
            if compound.IsNull():
                continue
        except Exception:
            pass
        compounds.append(compound)
    return compounds


def _clip_polyline_3d_to_z_band(
    *,
    polyline_3d: Sequence[Tuple[float, float, float]],
    z_low: float,
    z_high: float,
) -> List[List[Tuple[float, float]]]:
    if len(polyline_3d) < 2:
        return []
    low = min(z_low, z_high)
    high = max(z_low, z_high)
    segments: List[List[Tuple[float, float]]] = []
    for idx in range(len(polyline_3d) - 1):
        clipped = _clip_segment_3d_to_z_band(
            p0=polyline_3d[idx],
            p1=polyline_3d[idx + 1],
            z_low=low,
            z_high=high,
        )
        if clipped is None:
            continue
        q0 = occt_section.quantize_point(clipped[0][0], clipped[0][1])
        q1 = occt_section.quantize_point(clipped[1][0], clipped[1][1])
        if q0 == q1:
            continue
        segments.append([q0, q1])
    return segments


def _clip_segment_3d_to_z_band(
    *,
    p0: Tuple[float, float, float],
    p1: Tuple[float, float, float],
    z_low: float,
    z_high: float,
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]] | None:
    x0, y0, z0 = p0
    x1, y1, z1 = p1
    dz = z1 - z0

    t0 = 0.0
    t1 = 1.0
    eps = 1.0e-12
    if abs(dz) <= eps:
        if z_low <= z0 <= z_high:
            return p0, p1
        return None

    tz0 = (z_low - z0) / dz
    tz1 = (z_high - z0) / dz
    enter = min(tz0, tz1)
    exit = max(tz0, tz1)
    t0 = max(t0, enter)
    t1 = min(t1, exit)
    if t0 > t1:
        return None

    def _lerp(t: float) -> Tuple[float, float, float]:
        return (
            x0 + (x1 - x0) * t,
            y0 + (y1 - y0) * t,
            z0 + dz * t,
        )

    return _lerp(t0), _lerp(t1)


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

    # Hidden lines that coincide with visible lines read as drafting noise.
    visible_geom = {
        _typed_line_geometry_key(line)
        for line in kept
        if line.kind is not LineKind.HIDDEN
    }
    hidden_filtered = [
        line for line in owned_hidden if _typed_line_geometry_key(line) not in visible_geom
    ]
    kept.extend(hidden_filtered)
    return _deduplicate_typed_lines(kept)


def _deduplicate_typed_lines(lines: Sequence[TypedLine2D]) -> List[TypedLine2D]:
    deduped: List[TypedLine2D] = []
    seen = set()
    for line in lines:
        key = _typed_line_dedup_key(line)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(line)
    return deduped


def _typed_line_dedup_key(line: TypedLine2D):
    points = tuple((point.x, point.y) for point in line.points)
    canonical_points = _canonical_points(points, line.closed)
    return (
        line.kind.name,
        line.lineweight_class.name,
        line.source_ifc_class or "",
        line.closed,
        canonical_points,
    )


def _typed_line_geometry_key(line: TypedLine2D):
    points = tuple((point.x, point.y) for point in line.points)
    canonical_points = _canonical_points(points, line.closed)
    return (line.closed, canonical_points)


def _canonical_points(
    points: Tuple[Tuple[float, float], ...],
    closed: bool,
) -> Tuple[Tuple[float, float], ...]:
    if not points:
        return ()
    if not closed:
        reversed_points = tuple(reversed(points))
        return points if points <= reversed_points else reversed_points

    ring = points[:-1] if len(points) > 1 and points[0] == points[-1] else points
    if len(ring) < 3:
        reversed_points = tuple(reversed(points))
        return points if points <= reversed_points else reversed_points

    forward = _canonicalize_ring_orientation(ring)
    backward = _canonicalize_ring_orientation(tuple(reversed(ring)))
    best = forward if forward <= backward else backward
    return best + (best[0],)


def _canonicalize_ring_orientation(
    ring: Tuple[Tuple[float, float], ...],
) -> Tuple[Tuple[float, float], ...]:
    min_point = min(ring)
    candidates = []
    for idx, point in enumerate(ring):
        if point != min_point:
            continue
        candidates.append(ring[idx:] + ring[:idx])
    return min(candidates) if candidates else ring


def _polyline_sort_key(polyline: Sequence[Tuple[float, float]]):
    if not polyline:
        return ((), 0)
    return (tuple(polyline), len(polyline))


def _deduplicate_2d_polylines(
    polylines: Sequence[Sequence[Tuple[float, float]]],
) -> List[List[Tuple[float, float]]]:
    deduped: List[List[Tuple[float, float]]] = []
    seen = set()
    for polyline in polylines:
        if len(polyline) < 2:
            continue
        points = tuple(polyline)
        closed = len(points) > 2 and points[0] == points[-1]
        canonical_points = _canonical_points(points, closed)
        if canonical_points in seen:
            continue
        seen.add(canonical_points)
        deduped.append(list(canonical_points))
    deduped.sort(key=_polyline_sort_key)
    return deduped


def _looks_like_projected_hlr_polyline(
    polyline_3d: Sequence[Tuple[float, float, float]],
    *,
    z_tol: float = 1.0e-4,
) -> bool:
    if len(polyline_3d) < 2:
        return False
    zs = [point[2] for point in polyline_3d]
    z_span = max(zs) - min(zs)
    if z_span > z_tol:
        return False
    # Projector-space HLR output is typically centered near z=0.
    return abs(zs[0]) <= z_tol


def _polyline_3d_to_2d_segments(
    polyline_3d: Sequence[Tuple[float, float, float]],
) -> List[List[Tuple[float, float]]]:
    if len(polyline_3d) < 2:
        return []
    points_2d: List[Tuple[float, float]] = []
    last: Tuple[float, float] | None = None
    for x, y, _z in polyline_3d:
        point = occt_section.quantize_point(x, y)
        if point == last:
            continue
        points_2d.append(point)
        last = point
    if len(points_2d) < 2:
        return []
    segments: List[List[Tuple[float, float]]] = []
    for idx in range(len(points_2d) - 1):
        p0 = points_2d[idx]
        p1 = points_2d[idx + 1]
        if p0 == p1:
            continue
        segments.append([p0, p1])
    return segments
