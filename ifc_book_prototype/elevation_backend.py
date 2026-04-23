"""Elevation-view geometry (N/S/E/W).

This is the simplest correct-by-construction elevation backend: for every
element in ``include_classes`` across the whole model, it extracts the BRep
shape via OCCT, walks every edge, and projects the 3D sample points onto a
2D elevation plane chosen by ``view.view_kind``.

Axis mapping (viewer standing on the named side, looking toward the building):

  - elevation_north: viewer on +Y, looks -Y. (u,v) = ( +x,  +z )
  - elevation_south: viewer on -Y, looks +Y. (u,v) = ( -x,  +z )
  - elevation_east:  viewer on +X, looks -X. (u,v) = ( -y,  +z )
  - elevation_west:  viewer on -X, looks +X. (u,v) = ( +y,  +z )

Mirroring in S / E keeps each elevation reading "left-to-right" as the viewer
would expect when walking around the building. It does not attempt to match
any particular drafting convention beyond that.

No visibility classification — every edge is emitted as ``PROJECTED``.
Hidden-line suppression is Phase 3C step 3 (HLR) territory.

Without OCCT the public entry point returns an honest empty summary with a
note so the sheet still renders and the determinism gate stays green.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import occt_section
from ._ifc_index import build_storey_elevations, index_elements_by_storey
from .domain import (
    Bounds2D,
    ELEVATION_VIEW_KINDS,
    GeometrySummary,
    LineKind,
    LineweightClass,
    PlannedView,
    Point2D,
    StyleProfile,
    TypedLine2D,
    VIEW_KIND_ELEVATION_EAST,
    VIEW_KIND_ELEVATION_NORTH,
    VIEW_KIND_ELEVATION_SOUTH,
    VIEW_KIND_ELEVATION_WEST,
    ViewLinework,
    typed_line_sort_key,
)


__all__ = [
    "ElevationBackend",
    "axis_projector_for_view_kind",
    "is_elevation_view",
]


def is_elevation_view(view: PlannedView) -> bool:
    return view.view_kind in ELEVATION_VIEW_KINDS


ProjectFn = Callable[[float, float, float], Tuple[float, float]]


def axis_projector_for_view_kind(view_kind: str) -> ProjectFn:
    """Return ``(x, y, z) -> (u, v)`` for the given elevation kind."""
    if view_kind == VIEW_KIND_ELEVATION_NORTH:
        return lambda x, y, z: (x, z)
    if view_kind == VIEW_KIND_ELEVATION_SOUTH:
        return lambda x, y, z: (-x, z)
    if view_kind == VIEW_KIND_ELEVATION_EAST:
        return lambda x, y, z: (-y, z)
    if view_kind == VIEW_KIND_ELEVATION_WEST:
        return lambda x, y, z: (y, z)
    raise ValueError(f"Unsupported elevation view_kind: {view_kind!r}")


@dataclass
class ElevationBackend:
    """Stateful elevation geometry builder.

    Opens the IFC file once, caches the global element list, and serves
    ``build_view`` calls for elevation PlannedViews. For plan views this
    backend is not used — the pipeline keeps routing those to the composite
    geometry backend.
    """

    ifc_path: Path
    profile: StyleProfile

    name: str = "occt-elevation-edges"

    _model: object = field(init=False, default=None)
    _ifc_geom: object = field(init=False, default=None)
    _unit_scale: float = field(init=False, default=1.0)
    _elements: List[object] = field(init=False, default_factory=list)
    _available: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if not occt_section.OCCT_AVAILABLE:
            # We still instantiate — the pipeline always calls build_view for
            # elevation views, and we want it to return a deterministic empty
            # summary rather than raising. Keep _available False.
            return
        try:
            import ifcopenshell  # type: ignore
            import ifcopenshell.geom  # type: ignore
            from ifcopenshell.util.element import get_container  # type: ignore
            from ifcopenshell.util.unit import calculate_unit_scale  # type: ignore
        except Exception:
            return
        try:
            self._ifc_geom = ifcopenshell.geom
            self._model = ifcopenshell.open(str(self.ifc_path))
            self._unit_scale = float(calculate_unit_scale(self._model))
            # Elevations span the whole building — flatten the per-storey index.
            elements_by_storey = index_elements_by_storey(
                self._model,
                self.profile.floor_plan.include_classes,
                get_container,
            )
            flat: List[object] = []
            for storey, elements in sorted(elements_by_storey.items()):
                flat.extend(elements)
            # Deterministic order for projection.
            flat.sort(key=lambda el: (el.is_a(), getattr(el, "GlobalId", "") or "", el.id()))
            self._elements = flat
            self._available = True
        except Exception:
            self._available = False

    # ------------------------------------------------------------------
    def build_view(self, view: PlannedView) -> GeometrySummary:
        if not is_elevation_view(view):
            raise ValueError(
                f"ElevationBackend.build_view called on non-elevation view: {view.view_kind!r}"
            )
        if not self._available:
            return _empty_elevation_summary(
                view,
                backend_name=self.name,
                reason=(
                    "Elevation geometry requires the [occt] extra (pythonocc-core). "
                    "Install it and re-run to populate elevation views."
                ),
            )

        project = axis_projector_for_view_kind(view.view_kind)
        chord_tol = self.profile.floor_plan.cut_chord_tolerance_m
        budget_s = self.profile.floor_plan.occt_per_element_budget_s

        lines: List[TypedLine2D] = []
        per_class_counts: Dict[str, int] = {}
        for element in self._elements:
            ifc_class = element.is_a()
            global_id = getattr(element, "GlobalId", "") or ""
            try:
                polylines = occt_section.run_with_budget(
                    lambda el=element: _project_edges(self._ifc_geom, el, chord_tol, project),
                    budget_s,
                )
            except Exception:
                continue
            for polyline in polylines:
                if len(polyline) < 2:
                    continue
                lines.append(
                    TypedLine2D(
                        kind=LineKind.PROJECTED,
                        lineweight_class=LineweightClass.LIGHT,
                        points=[Point2D(x=u, y=v) for (u, v) in polyline],
                        closed=polyline[0] == polyline[-1] and len(polyline) > 2,
                        source_element=global_id,
                        source_ifc_class=ifc_class,
                    )
                )
                per_class_counts[ifc_class] = per_class_counts.get(ifc_class, 0) + 1

        lines.sort(key=typed_line_sort_key)
        bounds = _bounds_from_typed_lines(lines)
        counts_by_kind = {LineKind.PROJECTED.name: len(lines)}
        linework = ViewLinework(
            lines=lines,
            counts_by_kind=counts_by_kind,
            quantization_m=occt_section.QUANTIZATION_M,
        )
        notes = [
            f"{self.name} produced {len(lines)} projected line(s) from {len(self._elements)} candidate element(s).",
            "All edges are emitted as PROJECTED; hidden-line classification is Phase 3C step 3 (HLR).",
        ]
        return GeometrySummary(
            view_id=view.view_id,
            backend=self.name,
            cut_candidates={},
            projection_candidates=dict(sorted(per_class_counts.items())),
            source_elements=len(self._elements),
            path_count=0,
            bounds=bounds,
            paths=[],
            polygons=[],
            notes=notes,
            linework=linework,
            linework_counts=dict(counts_by_kind),
            feature_anchors=[],
            feature_anchor_counts={},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_elevation_summary(view: PlannedView, *, backend_name: str, reason: str) -> GeometrySummary:
    return GeometrySummary(
        view_id=view.view_id,
        backend=backend_name,
        cut_candidates={},
        projection_candidates={},
        source_elements=0,
        path_count=0,
        bounds=None,
        paths=[],
        polygons=[],
        notes=[reason],
        linework=None,
        linework_counts={},
        feature_anchors=[],
        feature_anchor_counts={},
    )


def _project_edges(
    ifc_geom_module,
    element,
    chord_tol_m: float,
    project: ProjectFn,
) -> List[List[Tuple[float, float]]]:
    """Walk every BRep edge of ``element``, project via ``project``, chain."""
    if not occt_section.OCCT_AVAILABLE:
        return []
    shape = occt_section.brep_from_ifc_element(ifc_geom_module, None, element)
    if shape is None:
        return []

    from OCC.Core.TopExp import TopExp_Explorer  # type: ignore
    from OCC.Core.TopAbs import TopAbs_EDGE  # type: ignore

    raw_segments: List[List[Tuple[float, float]]] = []
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    while explorer.More():
        edge = explorer.Current()
        explorer.Next()
        samples_3d = occt_section.edge_to_polyline_3d(edge, chord_tol_m)
        if len(samples_3d) < 2:
            continue
        projected: List[Tuple[float, float]] = []
        last: Optional[Tuple[float, float]] = None
        for (x, y, z) in samples_3d:
            u, v = project(x, y, z)
            qp = (occt_section.quantize(u), occt_section.quantize(v))
            if qp != last:
                projected.append(qp)
                last = qp
        if len(projected) < 2:
            continue
        # Drop degenerate (all-coincident) projections — an edge perpendicular
        # to the elevation plane collapses to a single point.
        if all(p == projected[0] for p in projected):
            continue
        raw_segments.append(projected)

    raw_segments.sort(key=lambda seg: (seg[0][0], seg[0][1], seg[-1][0], seg[-1][1], len(seg)))
    return [chain for chain in occt_section.chain_polylines(raw_segments) if len(chain) >= 2]


def _bounds_from_typed_lines(lines) -> Optional[Bounds2D]:
    if not lines:
        return None
    min_x = min(p.x for line in lines for p in line.points)
    min_y = min(p.y for line in lines for p in line.points)
    max_x = max(p.x for line in lines for p in line.points)
    max_y = max(p.y for line in lines for p in line.points)
    return Bounds2D(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)
