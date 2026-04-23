"""OCCT-aware geometry backends.

``OCCTSectionBackend`` produces typed ``CUT`` linework for the configured
``cut_classes`` using OCCT BRep section + a per-element wall-clock budget,
with a deterministic mesh-slice fallback.

``CompositeGeometryBackend`` composes OCCT (cut) with the existing
serializer backend (projection + back-compat ``paths``). The OCCT layer is
authoritative for cut geometry on the configured classes; the serializer
remains authoritative for everything else, so introducing OCCT does not
regress projection coverage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import geometry_projection, occt_section
from ._ifc_index import build_storey_elevations, index_elements_by_storey
from .domain import (
    Bounds2D,
    FeatureAnchor2D,
    GeometrySummary,
    LineKind,
    LineweightClass,
    Point2D,
    PlannedView,
    StyleProfile,
    TypedLine2D,
    ViewLinework,
    typed_line_sort_key,
)
from .feature_anchors import build_feature_anchors_by_storey, count_feature_anchors


# ---------------------------------------------------------------------------
# OCCT-only backend
# ---------------------------------------------------------------------------


@dataclass
class OCCTSectionBackend:
    ifc_path: Path
    profile: StyleProfile

    name: str = "occt-section"

    _model: object = field(init=False, default=None)
    _ifc_geom: object = field(init=False, default=None)
    _unit_scale: float = field(init=False, default=1.0)
    _storey_elevations: Dict[str, float] = field(init=False, default_factory=dict)
    _elements_by_storey: Dict[str, List[object]] = field(init=False, default_factory=dict)
    _feature_anchors_by_storey: Dict[str, List[FeatureAnchor2D]] = field(init=False, default_factory=dict)
    _mesh_settings: object = field(init=False, default=None)

    def __post_init__(self) -> None:
        if not occt_section.OCCT_AVAILABLE:
            raise RuntimeError("OCCT backend requested but pythonocc-core is not importable.")
        import ifcopenshell  # type: ignore
        import ifcopenshell.geom  # type: ignore
        from ifcopenshell.util.element import get_container  # type: ignore
        from ifcopenshell.util.unit import calculate_unit_scale  # type: ignore

        self._ifc_geom = ifcopenshell.geom
        self._model = ifcopenshell.open(str(self.ifc_path))
        self._unit_scale = float(calculate_unit_scale(self._model))
        self._storey_elevations = build_storey_elevations(self._model, self._unit_scale)
        self._elements_by_storey = index_elements_by_storey(
            self._model,
            self.profile.floor_plan.include_classes,
            get_container,
        )
        self._feature_anchors_by_storey = build_feature_anchors_by_storey(
            self._model,
            self._unit_scale,
            get_container,
        )
        self._mesh_settings = ifcopenshell.geom.settings()
        self._mesh_settings.set(self._mesh_settings.USE_WORLD_COORDS, True)

    # ------------------------------------------------------------------
    def build_view(self, view: PlannedView) -> GeometrySummary:
        rule = self.profile.floor_plan
        cut_class_set = set(rule.cut_classes)
        elements = [
            element
            for element in self._elements_by_storey.get(view.storey_name, [])
            if element.is_a() in cut_class_set
        ]
        plane = occt_section.CutPlane(
            z_m=self._storey_elevations.get(view.storey_name, view.storey_elevation_m or 0.0)
            + view.cut_plane_m,
        )
        report = occt_section.extract_cut_lines_report(
            ifc_geom_module=self._ifc_geom,
            elements=elements,
            plane=plane,
            per_element_budget_s=rule.occt_per_element_budget_s,
            chord_tol_m=rule.cut_chord_tolerance_m,
            fallback=self._mesh_slice_fallback,
        )
        lines = report.lines
        cut_counts: Dict[str, int] = {}
        for line in lines:
            if line.source_ifc_class:
                cut_counts[line.source_ifc_class] = cut_counts.get(line.source_ifc_class, 0) + 1
        bounds = _bounds_from_typed_lines(lines)
        linework = ViewLinework(
            lines=lines,
            counts_by_kind={"CUT": len(lines)},
            quantization_m=occt_section.QUANTIZATION_M,
        )
        notes = [
            f"OCCT BRep section produced {len(lines)} cut line(s) over {len(elements)} candidate element(s).",
        ]
        if report.fallback_events:
            notes.append(
                "OCCT fallback activated "
                f"{report.fallback_events} time(s): "
                f"{report.fallback_timeout_events} timeout(s), "
                f"{report.fallback_exception_events} exception(s), "
                f"{report.fallback_empty_events} empty fallback result(s)."
            )
            if report.fallback_by_class:
                pairs = [f"{class_name}:{count}" for class_name, count in sorted(report.fallback_by_class.items())]
                notes.append("OCCT fallback by class: " + ", ".join(pairs) + ".")
        feature_anchors = list(self._feature_anchors_by_storey.get(view.storey_name, []))
        bounds = bounds or _bounds_from_feature_anchors(feature_anchors)
        return GeometrySummary(
            view_id=view.view_id,
            backend=self.name,
            cut_candidates=dict(sorted(cut_counts.items())),
            projection_candidates={},
            source_elements=len(elements),
            path_count=0,
            bounds=bounds,
            paths=[],
            polygons=[],
            notes=notes,
            linework=linework,
            linework_counts={"CUT": len(lines)},
            fallback_events=report.fallback_events,
            fallback_by_class=dict(report.fallback_by_class),
            fallback_timeout_events=report.fallback_timeout_events,
            fallback_exception_events=report.fallback_exception_events,
            fallback_empty_events=report.fallback_empty_events,
            feature_anchors=feature_anchors,
            feature_anchor_counts=count_feature_anchors(feature_anchors),
        )

    # ------------------------------------------------------------------
    def _mesh_slice_fallback(self, element, plane_z: float) -> List[List[Tuple[float, float]]]:
        """Return list of 2D polylines (list of (x,y)) for an element via mesh slice.

        We triangulate the element, intersect each triangle with the cut plane,
        quantize the points and deterministically chain adjacent segments.
        """
        try:
            shape = self._ifc_geom.create_shape(self._mesh_settings, element)
        except Exception:
            return []

        verts = shape.geometry.verts
        faces = shape.geometry.faces
        segments: List[List[Tuple[float, float]]] = []
        for index in range(0, len(faces), 3):
            tri_indices = faces[index : index + 3]
            if len(tri_indices) < 3:
                continue
            p1 = _vertex_at(verts, tri_indices[0])
            p2 = _vertex_at(verts, tri_indices[1])
            p3 = _vertex_at(verts, tri_indices[2])
            tri_segments = _triangle_plane_segments(p1, p2, p3, plane_z)
            segments.extend(tri_segments)
        if not segments:
            return []
        segments.sort(key=_segment_sort_key)
        chains = occt_section.chain_polylines(segments)
        chains = [chain for chain in chains if len(chain) >= 2]
        chains.sort(key=_chain_sort_key)
        return chains


# ---------------------------------------------------------------------------
# Composite backend
# ---------------------------------------------------------------------------


@dataclass
class CompositeGeometryBackend:
    """Compose OCCT cut + serializer projection.

    OCCT is authoritative for cut linework on the configured ``cut_classes``.
    The serializer backend keeps producing legacy ``paths`` (back-compat) and
    its projection counts. Their outputs merge into a single ``GeometrySummary``
    where ``linework.lines`` carries OCCT cut + serializer projection (typed
    as PROJECTED/LIGHT).
    """

    occt: OCCTSectionBackend
    serializer: object  # IfcSerializerPlanBackend; left untyped to avoid a circular import

    name: str = "composite-occt+serializer"

    def build_view(self, view: PlannedView) -> GeometrySummary:
        occt_summary = self.occt.build_view(view)
        serializer_summary = self.serializer.build_view(view)

        merged_lines: List[TypedLine2D] = []
        if occt_summary.linework is not None:
            merged_lines.extend(occt_summary.linework.lines)

        # Phase 3C: owned projection/hidden lines (scaffold — empty until real
        # implementation lands). When ``own_projection`` is on, serializer
        # projection is suppressed even if owned output is empty; this is the
        # "own it or bust" contract documented in ``geometry_projection``.
        profile = getattr(self.occt, "profile", None)
        ifc_geom = getattr(self.occt, "_ifc_geom", None)
        storey_elevations = getattr(self.occt, "_storey_elevations", {}) or {}
        elements_by_storey = getattr(self.occt, "_elements_by_storey", {}) or {}
        own_projection_on = profile is not None and geometry_projection.owned_projection_enabled(profile)
        owned_projection: List[TypedLine2D] = []
        owned_hidden: List[TypedLine2D] = []
        if profile is not None:
            storey_z = storey_elevations.get(view.storey_name, 0.0)
            # Owned projection walks the same element set the cut extractor
            # considers — the same cut_classes filter would make sense here,
            # but step 1 deliberately walks ALL included_classes since the
            # projection target is beyond-cut geometry, not just cut elements.
            storey_elements = list(elements_by_storey.get(view.storey_name, []))
            owned_projection = geometry_projection.extract_owned_projection_lines(
                view=view,
                profile=profile,
                elements=storey_elements,
                ifc_geom_module=ifc_geom,
                storey_elevation_m=storey_z,
            )
            owned_hidden = geometry_projection.extract_owned_hidden_lines(
                view=view,
                profile=profile,
                elements=storey_elements,
                ifc_geom_module=ifc_geom,
                storey_elevation_m=storey_z,
            )

        if not own_projection_on:
            for path in serializer_summary.paths:
                if path.role != "projection":
                    continue
                if not path.points:
                    continue
                merged_lines.append(
                    TypedLine2D(
                        kind=LineKind.PROJECTED,
                        lineweight_class=LineweightClass.LIGHT,
                        points=list(path.points),
                        closed=path.closed,
                        source_ifc_class=path.ifc_class,
                    )
                )
        merged_lines.extend(owned_projection)
        merged_lines.extend(owned_hidden)
        merged_lines.sort(key=typed_line_sort_key)

        counts_by_kind: Dict[str, int] = {}
        for line in merged_lines:
            counts_by_kind[line.kind.name] = counts_by_kind.get(line.kind.name, 0) + 1

        linework = ViewLinework(
            lines=merged_lines,
            counts_by_kind=counts_by_kind,
            quantization_m=occt_section.QUANTIZATION_M,
        )

        bounds = _union_bounds(occt_summary.bounds, serializer_summary.bounds)
        merged_notes = sorted({*(occt_summary.notes or []), *(serializer_summary.notes or [])})
        feature_anchors = _merge_feature_anchors(
            serializer_summary.feature_anchors,
            occt_summary.feature_anchors,
        )
        bounds = bounds or _bounds_from_feature_anchors(feature_anchors)

        return GeometrySummary(
            view_id=view.view_id,
            backend=self.name,
            cut_candidates=dict(sorted(occt_summary.cut_candidates.items())),
            projection_candidates=dict(sorted(serializer_summary.projection_candidates.items())),
            source_elements=max(occt_summary.source_elements, serializer_summary.source_elements),
            path_count=serializer_summary.path_count,
            bounds=bounds,
            paths=list(serializer_summary.paths),  # back-compat
            polygons=list(serializer_summary.polygons),
            notes=merged_notes,
            linework=linework,
            linework_counts=dict(counts_by_kind),
            fallback_events=occt_summary.fallback_events,
            fallback_by_class=dict(occt_summary.fallback_by_class),
            fallback_timeout_events=occt_summary.fallback_timeout_events,
            fallback_exception_events=occt_summary.fallback_exception_events,
            fallback_empty_events=occt_summary.fallback_empty_events,
            feature_anchors=feature_anchors,
            feature_anchor_counts=count_feature_anchors(feature_anchors),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bounds_from_typed_lines(lines: Sequence[TypedLine2D]) -> Optional[Bounds2D]:
    if not lines:
        return None
    min_x = min(point.x for line in lines for point in line.points)
    min_y = min(point.y for line in lines for point in line.points)
    max_x = max(point.x for line in lines for point in line.points)
    max_y = max(point.y for line in lines for point in line.points)
    return Bounds2D(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def _union_bounds(a: Optional[Bounds2D], b: Optional[Bounds2D]) -> Optional[Bounds2D]:
    if a is None:
        return b
    if b is None:
        return a
    return Bounds2D(
        min_x=min(a.min_x, b.min_x),
        min_y=min(a.min_y, b.min_y),
        max_x=max(a.max_x, b.max_x),
        max_y=max(a.max_y, b.max_y),
    )


def _merge_feature_anchors(
    primary: Sequence[FeatureAnchor2D],
    secondary: Sequence[FeatureAnchor2D],
) -> List[FeatureAnchor2D]:
    merged: Dict[Tuple[str, str, float, float], FeatureAnchor2D] = {}
    for anchor in list(primary) + list(secondary):
        key = (
            anchor.ifc_class,
            anchor.source_element or "",
            round(anchor.anchor.x, 4),
            round(anchor.anchor.y, 4),
        )
        # Keep first item (primary wins).
        if key not in merged:
            merged[key] = anchor
    values = list(merged.values())
    values.sort(
        key=lambda item: (
            item.ifc_class,
            item.source_element or "",
            item.anchor.y,
            item.anchor.x,
        )
    )
    return values


def _bounds_from_feature_anchors(feature_anchors: Sequence[FeatureAnchor2D], padding_m: float = 2.0) -> Optional[Bounds2D]:
    if not feature_anchors:
        return None
    min_x = min(anchor.anchor.x for anchor in feature_anchors)
    min_y = min(anchor.anchor.y for anchor in feature_anchors)
    max_x = max(anchor.anchor.x for anchor in feature_anchors)
    max_y = max(anchor.anchor.y for anchor in feature_anchors)
    width = max_x - min_x
    height = max_y - min_y
    pad = max(padding_m, width * 0.1, height * 0.1)
    return Bounds2D(
        min_x=min_x - pad,
        min_y=min_y - pad,
        max_x=max_x + pad,
        max_y=max_y + pad,
    )


def _vertex_at(verts: Sequence[float], index: int) -> Tuple[float, float, float]:
    base = index * 3
    return float(verts[base]), float(verts[base + 1]), float(verts[base + 2])


def _triangle_plane_segments(
    p1: Tuple[float, float, float],
    p2: Tuple[float, float, float],
    p3: Tuple[float, float, float],
    plane_z: float,
) -> List[List[Tuple[float, float]]]:
    edges = ((p1, p2), (p2, p3), (p3, p1))
    segments: List[List[Tuple[float, float]]] = []
    points: List[Tuple[float, float]] = []
    eps = 1.0e-6
    for a, b in edges:
        az = a[2]
        bz = b[2]
        da = az - plane_z
        db = bz - plane_z
        if abs(da) <= eps and abs(db) <= eps:
            qa = occt_section.quantize_point(a[0], a[1])
            qb = occt_section.quantize_point(b[0], b[1])
            if qa != qb:
                segment = [qa, qb]
                segment.sort()
                segments.append(segment)
            continue
        if da * db < -eps * eps:
            t = (plane_z - az) / (bz - az)
            x = a[0] + t * (b[0] - a[0])
            y = a[1] + t * (b[1] - a[1])
            points.append(occt_section.quantize_point(x, y))
            continue
        if abs(da) <= eps:
            points.append(occt_section.quantize_point(a[0], a[1]))
            continue
        if abs(db) <= eps:
            points.append(occt_section.quantize_point(b[0], b[1]))
            continue
    unique_points = sorted(set(points))
    if len(unique_points) >= 2:
        segments.append([unique_points[0], unique_points[1]])
    return segments


def _segment_sort_key(segment: Sequence[Tuple[float, float]]):
    a, b = segment[0], segment[-1]
    return (a[0], a[1], b[0], b[1], len(segment))


def _chain_sort_key(chain: Sequence[Tuple[float, float]]):
    first = chain[0]
    return (first[0], first[1], len(chain))
