"""Elevation-view geometry (N/S/E/W).

Two extraction paths:

  OCCT path (best quality, requires [occt] extra):
    Walk every BRep edge of each element's shape and project to the elevation
    plane. Gives clean, exact geometry.

  Triangulation path (no extra deps, uses ifcopenshell that plan-view already needs):
    Get the triangulated mesh of each element via ifcopenshell.geom, then keep
    only *silhouette* and *feature* edges: edges where adjacent faces are on
    opposite sides of the view direction, or where adjacent faces meet at a
    sharp angle.  This produces elevation outlines without OCCT.

Axis mapping (viewer standing on the named side, looking toward the building):

  - elevation_north: viewer on +Y, looks -Y. (u,v) = ( +x,  +z )
  - elevation_south: viewer on -Y, looks +Y. (u,v) = ( -x,  +z )
  - elevation_east:  viewer on +X, looks -X. (u,v) = ( -y,  +z )
  - elevation_west:  viewer on -X, looks +X. (u,v) = ( +y,  +z )
"""
from __future__ import annotations

import math
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

# Unit view-from vectors (toward the viewer, i.e. the outward normal of the
# viewing plane). Used for silhouette-edge classification.
_VIEW_FROM: Dict[str, Tuple[float, float, float]] = {
    VIEW_KIND_ELEVATION_NORTH: (0.0,  1.0, 0.0),
    VIEW_KIND_ELEVATION_SOUTH: (0.0, -1.0, 0.0),
    VIEW_KIND_ELEVATION_EAST:  (1.0,  0.0, 0.0),
    VIEW_KIND_ELEVATION_WEST:  (-1.0, 0.0, 0.0),
}

# Cosine threshold below which two adjacent face normals are considered a
# "feature edge" (sharp corner) worth drawing even when not a silhouette.
_FEATURE_EDGE_COS = 0.7   # ≈ 45 °


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

    Opens the IFC file once and serves ``build_view`` calls for all four
    elevation PlannedViews.  Prefers the OCCT path (BRep edges) when OCCT is
    installed; falls back to the triangulation path (silhouette + feature
    edges from the ifcopenshell mesh) when it is not.
    """

    ifc_path: Path
    profile: StyleProfile

    name: str = "elevation-backend"

    _model: object = field(init=False, default=None)
    _ifc_geom: object = field(init=False, default=None)
    _tri_settings: object = field(init=False, default=None)
    _unit_scale: float = field(init=False, default=1.0)
    _elements: List[object] = field(init=False, default_factory=list)
    _available: bool = field(init=False, default=False)       # OCCT ready
    _tri_available: bool = field(init=False, default=False)   # triangulation ready

    def __post_init__(self) -> None:
        # Phase 1: open the IFC file with ifcopenshell (required for both paths).
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
            elements_by_storey = index_elements_by_storey(
                self._model,
                self.profile.floor_plan.include_classes,
                get_container,
            )
            flat: List[object] = []
            for _storey, elems in sorted(elements_by_storey.items()):
                flat.extend(elems)
            flat.sort(key=lambda el: (el.is_a(), getattr(el, "GlobalId", "") or "", el.id()))
            self._elements = flat

            tri_settings = ifcopenshell.geom.settings()
            tri_settings.set(tri_settings.USE_WORLD_COORDS, True)
            self._tri_settings = tri_settings
            self._tri_available = True
        except Exception:
            return

        # Phase 2: upgrade to OCCT if available.
        if occt_section.OCCT_AVAILABLE:
            self._available = True
            self.name = "occt-elevation-edges"
        else:
            self.name = "tri-elevation-edges"

    # ------------------------------------------------------------------
    def build_view(self, view: PlannedView) -> GeometrySummary:
        if not is_elevation_view(view):
            raise ValueError(
                f"ElevationBackend.build_view called on non-elevation view: {view.view_kind!r}"
            )

        project = axis_projector_for_view_kind(view.view_kind)

        if self._available:
            lines, per_class_counts = self._build_occt(view, project)
            note_extra = "All edges are emitted as PROJECTED; hidden-line classification is Phase 3C step 3 (HLR)."
        elif self._tri_available:
            lines, per_class_counts = self._build_triangulated(view.view_kind, project)
            note_extra = "Silhouette + feature edges from triangulated mesh (ifcopenshell, no OCCT)."
        else:
            return _empty_elevation_summary(
                view,
                backend_name=self.name,
                reason=(
                    "Elevation geometry requires ifcopenshell (for triangulation) "
                    "or the [occt] extra for full BRep quality."
                ),
            )

        lines.sort(key=typed_line_sort_key)
        bounds = _bounds_from_typed_lines(lines)
        counts_by_kind = {LineKind.PROJECTED.name: len(lines)}
        quant = occt_section.QUANTIZATION_M if occt_section.OCCT_AVAILABLE else 1e-5
        linework = ViewLinework(
            lines=lines,
            counts_by_kind=counts_by_kind,
            quantization_m=quant,
        )
        notes = [
            f"{self.name} produced {len(lines)} line(s) from {len(self._elements)} element(s).",
            note_extra,
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

    # ------------------------------------------------------------------
    # OCCT path (original high-quality)
    # ------------------------------------------------------------------
    def _build_occt(
        self, view: PlannedView, project: ProjectFn
    ) -> Tuple[List[TypedLine2D], Dict[str, int]]:
        chord_tol = self.profile.floor_plan.cut_chord_tolerance_m
        budget_s = self.profile.floor_plan.occt_per_element_budget_s
        lines: List[TypedLine2D] = []
        per_class_counts: Dict[str, int] = {}
        for element in self._elements:
            ifc_class = element.is_a()
            global_id = getattr(element, "GlobalId", "") or ""
            try:
                polylines = occt_section.run_with_budget(
                    lambda el=element: _project_edges_occt(self._ifc_geom, el, chord_tol, project),
                    budget_s,
                )
            except Exception:
                continue
            for polyline in polylines:
                if len(polyline) < 2:
                    continue
                lines.append(TypedLine2D(
                    kind=LineKind.PROJECTED,
                    lineweight_class=LineweightClass.LIGHT,
                    points=[Point2D(x=u, y=v) for (u, v) in polyline],
                    closed=polyline[0] == polyline[-1] and len(polyline) > 2,
                    source_element=global_id,
                    source_ifc_class=ifc_class,
                ))
                per_class_counts[ifc_class] = per_class_counts.get(ifc_class, 0) + 1
        return lines, per_class_counts

    # ------------------------------------------------------------------
    # Triangulation path (silhouette + feature edges, no OCCT required)
    # ------------------------------------------------------------------
    def _build_triangulated(
        self, view_kind: str, project: ProjectFn
    ) -> Tuple[List[TypedLine2D], Dict[str, int]]:
        view_from = _VIEW_FROM.get(view_kind, (0.0, 1.0, 0.0))
        lines: List[TypedLine2D] = []
        per_class_counts: Dict[str, int] = {}
        seen_geom: set = set()

        for element in self._elements:
            ifc_class = element.is_a()
            global_id = getattr(element, "GlobalId", "") or ""
            try:
                shape = self._ifc_geom.create_shape(self._tri_settings, element)
                verts_flat = shape.geometry.verts   # flat x0,y0,z0,...
                faces_flat = shape.geometry.faces   # flat i0,i1,i2,...
            except Exception:
                continue

            n_verts = len(verts_flat) // 3
            n_faces = len(faces_flat) // 3
            if n_verts < 3 or n_faces < 1:
                continue

            edge_pairs = _silhouette_edges(verts_flat, faces_flat, n_verts, n_faces, view_from)

            emitted = 0
            for a, b in edge_pairs:
                ax = verts_flat[a * 3];     ay = verts_flat[a * 3 + 1]; az = verts_flat[a * 3 + 2]
                bx = verts_flat[b * 3];     by = verts_flat[b * 3 + 1]; bz = verts_flat[b * 3 + 2]
                u0, v0 = project(ax, ay, az)
                u1, v1 = project(bx, by, bz)
                qu0 = _qround(u0); qv0 = _qround(v0)
                qu1 = _qround(u1); qv1 = _qround(v1)
                if (qu0, qv0) == (qu1, qv1):
                    continue
                key = (min((qu0, qv0), (qu1, qv1)), max((qu0, qv0), (qu1, qv1)))
                if key in seen_geom:
                    continue
                seen_geom.add(key)
                lines.append(TypedLine2D(
                    kind=LineKind.PROJECTED,
                    lineweight_class=LineweightClass.LIGHT,
                    points=[Point2D(x=qu0, y=qv0), Point2D(x=qu1, y=qv1)],
                    source_element=global_id,
                    source_ifc_class=ifc_class,
                ))
                emitted += 1
            if emitted:
                per_class_counts[ifc_class] = per_class_counts.get(ifc_class, 0) + emitted

        return lines, per_class_counts


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

_QUANT = 1e-4   # 0.1 mm quantization for triangulation path


def _qround(v: float) -> float:
    return round(v / _QUANT) * _QUANT


def _cross3(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot3(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm3(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    mag = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if mag < 1.0e-12:
        return (0.0, 0.0, 0.0)
    return (v[0] / mag, v[1] / mag, v[2] / mag)


def _silhouette_edges(
    verts_flat: object,
    faces_flat: object,
    n_verts: int,
    n_faces: int,
    view_from: Tuple[float, float, float],
) -> List[Tuple[int, int]]:
    """Return edge index pairs that are silhouette or feature edges.

    Silhouette: one adjacent face facing the viewer, the other facing away.
    Feature:    both faces on the same side but meeting at angle > ~45°.
    Boundary:   only one adjacent face (open mesh / hole).
    """
    # Pre-read vertices
    pts: List[Tuple[float, float, float]] = [
        (float(verts_flat[i * 3]), float(verts_flat[i * 3 + 1]), float(verts_flat[i * 3 + 2]))
        for i in range(n_verts)
    ]

    # Compute face normals and view-dot for each face
    face_normals: List[Tuple[float, float, float]] = []
    face_dots: List[float] = []
    for f in range(n_faces):
        i0 = int(faces_flat[f * 3])
        i1 = int(faces_flat[f * 3 + 1])
        i2 = int(faces_flat[f * 3 + 2])
        v0, v1, v2 = pts[i0], pts[i1], pts[i2]
        e1 = (v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2])
        e2 = (v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2])
        n = _norm3(_cross3(e1, e2))
        face_normals.append(n)
        face_dots.append(_dot3(n, view_from))

    # Build edge → adjacent face indices
    edge_faces: Dict[Tuple[int, int], List[int]] = {}
    for f in range(n_faces):
        i0 = int(faces_flat[f * 3])
        i1 = int(faces_flat[f * 3 + 1])
        i2 = int(faces_flat[f * 3 + 2])
        for a, b in ((i0, i1), (i1, i2), (i2, i0)):
            key = (min(a, b), max(a, b))
            edge_faces.setdefault(key, []).append(f)

    keep: List[Tuple[int, int]] = []
    for (a, b), face_idxs in edge_faces.items():
        if len(face_idxs) == 1:
            keep.append((a, b))          # boundary edge
            continue
        d0 = face_dots[face_idxs[0]]
        d1 = face_dots[face_idxs[1]]
        # Silhouette: faces on opposite sides of the view plane
        if d0 * d1 < 0.0:
            keep.append((a, b))
            continue
        # Feature edge: sharp angle between adjacent faces
        n0 = face_normals[face_idxs[0]]
        n1 = face_normals[face_idxs[1]]
        if abs(_dot3(n0, n1)) < _FEATURE_EDGE_COS:
            keep.append((a, b))

    return keep


def _project_edges_occt(
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
        if all(p == projected[0] for p in projected):
            continue
        raw_segments.append(projected)

    raw_segments.sort(key=lambda seg: (seg[0][0], seg[0][1], seg[-1][0], seg[-1][1], len(seg)))
    return [chain for chain in occt_section.chain_polylines(raw_segments) if len(chain) >= 2]


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


def _bounds_from_typed_lines(lines: List[TypedLine2D]) -> Optional[Bounds2D]:
    if not lines:
        return None
    min_x = min(p.x for line in lines for p in line.points)
    min_y = min(p.y for line in lines for p in line.points)
    max_x = max(p.x for line in lines for p in line.points)
    max_y = max(p.y for line in lines for p in line.points)
    return Bounds2D(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)
