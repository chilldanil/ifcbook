from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree

from ._ifc_index import build_storey_elevations, index_elements_by_storey
from .domain import Bounds2D, GeometrySummary, Point2D, PlannedView, VectorPath, VectorPolygon


SVG_NS = "http://www.w3.org/2000/svg"
IFC_NS = "http://www.ifcopenshell.org/ns"
PATH_TOKEN_RE = re.compile(r"[MLHVZmlhvz]|-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
PRIMARY_CUT_CLASSES = frozenset({"IfcWall", "IfcSlab"})


class NullGeometryBackend:
    name = "null"

    def build_view(self, view: PlannedView) -> GeometrySummary:
        notes = [
            "No geometry backend is available for the current interpreter.",
            "Activate the local virtualenv or install ifcopenshell to enable real model extraction.",
        ]
        return GeometrySummary(
            view_id=view.view_id,
            backend=self.name,
            cut_candidates={},
            projection_candidates={},
            source_elements=0,
            path_count=0,
            bounds=None,
            paths=[],
            polygons=[],
            notes=notes,
        )


def create_geometry_backend(ifc_path: Path, included_classes: Iterable[str], profile=None):
    """Pick the best available geometry backend.

    Precedence:
      1. CompositeGeometryBackend (OCCT cut + serializer projection) — only when
         the [occt] extra is installed AND a StyleProfile is supplied so the
         OCCT layer can read its budget and chord tolerance.
      2. IfcSerializerPlanBackend (legacy primary).
      3. IfcMeshPlanBackend (mesh-footprint fallback).
      4. NullGeometryBackend.
    """
    included = list(included_classes)
    if profile is not None:
        try:
            from . import occt_section  # local import; safe even without OCCT
            if occt_section.OCCT_AVAILABLE:
                from .geometry_occt import CompositeGeometryBackend, OCCTSectionBackend
                serializer = IfcSerializerPlanBackend(ifc_path=ifc_path, included_classes=included)
                occt = OCCTSectionBackend(ifc_path=ifc_path, profile=profile)
                return CompositeGeometryBackend(occt=occt, serializer=serializer)
        except Exception:
            # Any failure in the OCCT path falls through to the serializer path.
            pass
    try:
        return IfcSerializerPlanBackend(ifc_path=ifc_path, included_classes=included)
    except Exception:
        pass
    try:
        return IfcMeshPlanBackend(ifc_path=ifc_path, included_classes=included)
    except Exception:
        return NullGeometryBackend()


@dataclass(frozen=True)
class _PreparedStoreyLinework:
    bounds: Optional[Bounds2D]
    paths: List[VectorPath]
    cut_counts: Dict[str, int]
    projection_counts: Dict[str, int]
    classified_groups: int
    notes: List[str]


@dataclass
class IfcSerializerPlanBackend:
    ifc_path: Path
    included_classes: List[str]

    def __post_init__(self) -> None:
        import ifcopenshell  # type: ignore
        import ifcopenshell.draw  # type: ignore
        from ifcopenshell.util.element import get_container  # type: ignore
        from ifcopenshell.util.unit import calculate_unit_scale  # type: ignore

        self._ifcopenshell = ifcopenshell
        self._draw = ifcopenshell.draw
        self._get_container = get_container
        self._model = ifcopenshell.open(str(self.ifc_path))
        self._unit_scale = float(calculate_unit_scale(self._model))
        self._storey_elevations = build_storey_elevations(self._model, self._unit_scale)
        self._elements_by_storey = index_elements_by_storey(
            self._model,
            self.included_classes,
            self._get_container,
        )
        self._storey_linework = self._build_storey_linework()

    def build_view(self, view: PlannedView) -> GeometrySummary:
        storey_linework = self._storey_linework.get(view.storey_name)
        indexed_elements = len(self._elements_by_storey.get(view.storey_name, []))
        if storey_linework is None:
            notes = [
                "IfcOpenShell SVG floorplan serializer did not return a matching storey group for this view.",
            ]
            return GeometrySummary(
                view_id=view.view_id,
                backend="ifcopenshell-svg-floorplan",
                cut_candidates={},
                projection_candidates={},
                source_elements=indexed_elements,
                path_count=0,
                bounds=None,
                paths=[],
                polygons=[],
                notes=notes,
            )

        source_elements = max(indexed_elements, storey_linework.classified_groups)
        return GeometrySummary(
            view_id=view.view_id,
            backend="ifcopenshell-svg-floorplan",
            cut_candidates=dict(sorted(storey_linework.cut_counts.items())),
            projection_candidates=dict(sorted(storey_linework.projection_counts.items())),
            source_elements=source_elements,
            path_count=len(storey_linework.paths),
            bounds=storey_linework.bounds,
            paths=storey_linework.paths,
            polygons=[],
            notes=list(storey_linework.notes),
        )

    def _build_storey_linework(self) -> Dict[str, _PreparedStoreyLinework]:
        settings = self._draw.draw_settings()
        settings.width = 297.0
        settings.height = 420.0
        settings.scale = 1.0 / 100.0
        settings.auto_floorplan = True
        settings.include_projection = True
        settings.cells = False
        settings.include_entities = ",".join(self.included_classes)

        svg_data = self._draw.main(settings, [self._model], merge_projection=False)
        if isinstance(svg_data, bytes):
            svg_text = svg_data.decode("utf-8")
        else:
            svg_text = svg_data

        root = ElementTree.fromstring(svg_text)
        storey_groups = [
            element
            for element in list(root)
            if _local_name(element.tag) == "g" and "IfcBuildingStorey" in element.attrib.get("class", "").split()
        ]
        if not storey_groups:
            raise RuntimeError("IfcOpenShell SVG serializer returned no storey groups.")

        prepared: Dict[str, _PreparedStoreyLinework] = {}
        for storey_group in storey_groups:
            storey_name = storey_group.attrib.get(f"{{{IFC_NS}}}name", "").strip()
            if not storey_name:
                continue
            prepared[storey_name] = self._prepare_storey_group(storey_name, storey_group)
        return prepared

    def _prepare_storey_group(
        self,
        storey_name: str,
        storey_group: ElementTree.Element,
    ) -> _PreparedStoreyLinework:
        paths: List[VectorPath] = []
        cut_counts: Dict[str, int] = {}
        projection_counts: Dict[str, int] = {}
        unsupported_commands = set()
        projection_groups = 0
        classified_groups = 0

        for group in storey_group.iter():
            if group is storey_group or _local_name(group.tag) != "g":
                continue
            role, ifc_class = _classify_group(group.attrib.get("class", ""))
            if role is None:
                continue
            classified_groups += 1
            if role == "cut" and ifc_class:
                cut_counts[ifc_class] = cut_counts.get(ifc_class, 0) + 1
            elif role == "projection":
                projection_groups += 1
                if ifc_class:
                    projection_counts[ifc_class] = projection_counts.get(ifc_class, 0) + 1

            for path_element in group.iter():
                if _local_name(path_element.tag) != "path":
                    continue
                parsed_paths, path_commands = _parse_svg_path(path_element.attrib.get("d", ""), role, ifc_class)
                paths.extend(parsed_paths)
                unsupported_commands.update(path_commands)

        paths.sort(key=_path_sort_key)
        notes = [
            f"IfcOpenShell SVG floorplan serializer extracted {len(paths)} line path(s) for {storey_name}.",
            "This backend uses IfcOpenShell hidden-line floorplan output instead of triangulated footprint unions.",
        ]
        if projection_groups and not projection_counts:
            notes.append(
                "Projection linework is emitted as a merged storey group in this serializer mode, so per-class projection counts are unavailable."
            )
        if unsupported_commands:
            notes.append(
                "Ignored unsupported SVG path commands from the serializer: "
                + ", ".join(sorted(unsupported_commands))
                + "."
            )
        bounds = _bounds_from_paths(paths)
        return _PreparedStoreyLinework(
            bounds=bounds,
            paths=paths,
            cut_counts=cut_counts,
            projection_counts=projection_counts,
            classified_groups=classified_groups,
            notes=notes,
        )


@dataclass
class IfcMeshPlanBackend:
    ifc_path: Path
    included_classes: List[str]

    def __post_init__(self) -> None:
        import ifcopenshell  # type: ignore
        import ifcopenshell.geom  # type: ignore
        from ifcopenshell.util.element import get_container  # type: ignore
        from ifcopenshell.util.unit import calculate_unit_scale  # type: ignore

        self._ifcopenshell = ifcopenshell
        self._geom = ifcopenshell.geom
        self._get_container = get_container
        self._model = ifcopenshell.open(str(self.ifc_path))
        self._unit_scale = float(calculate_unit_scale(self._model))
        self._settings = ifcopenshell.geom.settings()
        self._settings.set(self._settings.USE_WORLD_COORDS, True)
        self._storey_elevations = build_storey_elevations(self._model, self._unit_scale)
        self._elements_by_storey = index_elements_by_storey(
            self._model,
            self.included_classes,
            self._get_container,
        )

    def build_view(self, view: PlannedView) -> GeometrySummary:
        from shapely.geometry import Polygon  # type: ignore
        from shapely.ops import unary_union  # type: ignore

        storey_elevation = self._storey_elevations.get(view.storey_name, view.storey_elevation_m or 0.0)
        plane_z = storey_elevation + view.cut_plane_m
        band_low = storey_elevation - view.view_depth_below_m
        band_high = plane_z + view.overhead_depth_above_m

        candidate_elements = list(self._elements_by_storey.get(view.storey_name, []))
        cut_parts = []
        projection_parts = []
        cut_counts: Dict[str, int] = {}
        projection_counts: Dict[str, int] = {}
        skipped = 0

        for element in candidate_elements:
            result = self._extract_element_footprints(
                element=element,
                plane_z=plane_z,
                band_low=band_low,
                band_high=band_high,
                polygon_factory=Polygon,
                unary_union=unary_union,
            )
            if result is None:
                skipped += 1
                continue

            class_name, cut_geometry, projection_geometry = result
            if cut_geometry is not None and not cut_geometry.is_empty:
                cut_parts.append(cut_geometry)
                cut_counts[class_name] = cut_counts.get(class_name, 0) + 1
            if projection_geometry is not None and not projection_geometry.is_empty:
                projection_parts.append(projection_geometry)
                projection_counts[class_name] = projection_counts.get(class_name, 0) + 1

        cut_union = unary_union(cut_parts) if cut_parts else None
        projection_union = unary_union(projection_parts) if projection_parts else None
        polygons = []
        polygons.extend(_to_vector_polygons(cut_union, "cut"))
        polygons.extend(_to_vector_polygons(projection_union, "projection"))
        bounds = _merge_bounds([cut_union, projection_union])

        notes = [
            f"IfcOpenShell mesh-projection backend on {len(candidate_elements)} storey-contained elements.",
            "Serializer-based floorplan extraction was unavailable, so the pipeline fell back to projected triangulated footprints.",
        ]
        if skipped:
            notes.append(f"Skipped {skipped} elements because shape extraction or footprint generation failed.")

        return GeometrySummary(
            view_id=view.view_id,
            backend="ifcopenshell-mesh-plan",
            cut_candidates=dict(sorted(cut_counts.items())),
            projection_candidates=dict(sorted(projection_counts.items())),
            source_elements=len(candidate_elements),
            path_count=0,
            bounds=bounds,
            paths=[],
            polygons=polygons,
            notes=notes,
        )

    def _extract_element_footprints(self, element, plane_z, band_low, band_high, polygon_factory, unary_union):
        try:
            shape = self._geom.create_shape(self._settings, element)
        except Exception:
            return None

        verts = shape.geometry.verts
        faces = shape.geometry.faces
        class_name = element.is_a()
        all_polygons = []
        element_zmin = None
        element_zmax = None

        for index in range(0, len(faces), 3):
            tri_indices = faces[index : index + 3]
            p1 = _vertex_at(verts, tri_indices[0])
            p2 = _vertex_at(verts, tri_indices[1])
            p3 = _vertex_at(verts, tri_indices[2])
            zmin = min(p1[2], p2[2], p3[2])
            zmax = max(p1[2], p2[2], p3[2])
            element_zmin = zmin if element_zmin is None else min(element_zmin, zmin)
            element_zmax = zmax if element_zmax is None else max(element_zmax, zmax)

            polygon = polygon_factory([(p1[0], p1[1]), (p2[0], p2[1]), (p3[0], p3[1])])
            if polygon.is_empty or polygon.area <= 1e-7:
                continue
            all_polygons.append(polygon)

        if not all_polygons or element_zmin is None or element_zmax is None:
            return class_name, None, None

        try:
            element_footprint = unary_union(all_polygons)
        except Exception:
            return class_name, None, None

        if element_footprint is not None and not element_footprint.is_empty:
            element_footprint = element_footprint.simplify(0.005, preserve_topology=True)

        cut_geometry = None
        projection_geometry = None
        if element_zmin <= plane_z <= element_zmax:
            cut_geometry = element_footprint
        elif element_zmax >= band_low and element_zmin <= band_high:
            projection_geometry = element_footprint

        return class_name, cut_geometry, projection_geometry


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _classify_group(class_name: str) -> Tuple[Optional[str], Optional[str]]:
    tokens = class_name.split()
    if not tokens:
        return None, None
    role = None
    if "cut" in tokens:
        role = "cut"
    elif "projection" in tokens:
        role = "projection"
    if role is None:
        return None, None
    ifc_class = next((token for token in tokens if token.startswith("Ifc")), None)
    return role, ifc_class


def _parse_svg_path(path_data: str, role: str, ifc_class: Optional[str]) -> Tuple[List[VectorPath], set[str]]:
    if not path_data:
        return [], set()

    tokens = PATH_TOKEN_RE.findall(path_data)
    if not tokens:
        return [], set()

    paths: List[VectorPath] = []
    unsupported_commands = set()
    current_points: List[Tuple[float, float]] = []
    current_point = (0.0, 0.0)
    active_command = ""
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            active_command = token
            index += 1
        if not active_command:
            break

        if active_command in "Zz":
            vector_path = _finalize_path(current_points, role, ifc_class, force_closed=True)
            if vector_path is not None:
                paths.append(vector_path)
                current_point = (vector_path.points[0].x, vector_path.points[0].y)
            current_points = []
            active_command = ""
            continue

        params: List[float] = []
        while index < len(tokens) and not tokens[index].isalpha():
            params.append(float(tokens[index]))
            index += 1

        if active_command in "Mm":
            if len(params) < 2:
                continue
            if current_points:
                vector_path = _finalize_path(current_points, role, ifc_class, force_closed=False)
                if vector_path is not None:
                    paths.append(vector_path)
                current_points = []
            current_point = _path_point(current_point, params[0], params[1], active_command.islower())
            current_points = [current_point]
            for point_index in range(2, len(params), 2):
                if point_index + 1 >= len(params):
                    break
                current_point = _path_point(current_point, params[point_index], params[point_index + 1], active_command.islower())
                current_points.append(current_point)
            continue

        if active_command in "Ll":
            for point_index in range(0, len(params), 2):
                if point_index + 1 >= len(params):
                    break
                current_point = _path_point(current_point, params[point_index], params[point_index + 1], active_command.islower())
                current_points.append(current_point)
            continue

        if active_command in "Hh":
            for value in params:
                x = current_point[0] + value if active_command == "h" else value
                current_point = (x, current_point[1])
                current_points.append(current_point)
            continue

        if active_command in "Vv":
            for value in params:
                y = current_point[1] + value if active_command == "v" else value
                current_point = (current_point[0], y)
                current_points.append(current_point)
            continue

        unsupported_commands.add(active_command.upper())

    if current_points:
        vector_path = _finalize_path(current_points, role, ifc_class, force_closed=False)
        if vector_path is not None:
            paths.append(vector_path)

    return paths, unsupported_commands


def _path_point(current_point: Tuple[float, float], x: float, y: float, relative: bool) -> Tuple[float, float]:
    if relative:
        return current_point[0] + x, current_point[1] + y
    return x, y


def _finalize_path(
    raw_points: List[Tuple[float, float]],
    role: str,
    ifc_class: Optional[str],
    force_closed: bool,
) -> Optional[VectorPath]:
    if len(raw_points) < 2:
        return None
    closed = force_closed or _points_close(raw_points[0], raw_points[-1])
    normalized_points = list(raw_points[:-1] if closed and _points_close(raw_points[0], raw_points[-1]) else raw_points)
    if len(normalized_points) < 2:
        return None
    points = [Point2D(x=round(point[0], 4), y=round(point[1], 4)) for point in normalized_points]
    return VectorPath(role=role, points=points, closed=closed, ifc_class=ifc_class)


def _points_close(a: Tuple[float, float], b: Tuple[float, float], tolerance: float = 1.0e-6) -> bool:
    return abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance


def _path_sort_key(path: VectorPath) -> Tuple[str, str, float, float, int]:
    start = path.points[0]
    return (
        path.role,
        path.ifc_class or "",
        start.x,
        start.y,
        len(path.points),
    )


def _bounds_from_paths(paths: List[VectorPath]) -> Optional[Bounds2D]:
    if not paths:
        return None
    min_x = min(point.x for path in paths for point in path.points)
    min_y = min(point.y for path in paths for point in path.points)
    max_x = max(point.x for path in paths for point in path.points)
    max_y = max(point.y for path in paths for point in path.points)
    return Bounds2D(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def _vertex_at(verts: Tuple[float, ...], index: int) -> Tuple[float, float, float]:
    base = index * 3
    return float(verts[base]), float(verts[base + 1]), float(verts[base + 2])


def _merge_bounds(geometries: Iterable[object]) -> Optional[Bounds2D]:
    bounds = []
    for geometry in geometries:
        if geometry is None or geometry.is_empty:
            continue
        bounds.append(geometry.bounds)
    if not bounds:
        return None
    min_x = min(bound[0] for bound in bounds)
    min_y = min(bound[1] for bound in bounds)
    max_x = max(bound[2] for bound in bounds)
    max_y = max(bound[3] for bound in bounds)
    return Bounds2D(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def _to_vector_polygons(geometry, role: str) -> List[VectorPolygon]:
    if geometry is None or geometry.is_empty:
        return []

    polygons = []
    geometry_type = geometry.geom_type
    if geometry_type == "Polygon":
        polygons.append(geometry)
    elif geometry_type == "MultiPolygon":
        polygons.extend(list(geometry.geoms))
    elif geometry_type == "GeometryCollection":
        for child in geometry.geoms:
            polygons.extend(_to_vector_polygons(child, role))
        return polygons
    else:
        return []

    vector_polygons: List[VectorPolygon] = []
    sortable = []
    for polygon in polygons:
        if polygon.is_empty or polygon.area <= 1e-6:
            continue
        exterior = _coords_to_points(list(polygon.exterior.coords))
        if len(exterior) < 3:
            continue
        rings = [exterior]
        for interior in polygon.interiors:
            interior_points = _coords_to_points(list(interior.coords))
            if len(interior_points) >= 3:
                rings.append(interior_points)
        sortable.append((polygon.bounds, -polygon.area, rings))

    sortable.sort(key=lambda item: (round(item[0][0], 4), round(item[0][1], 4), item[1]))
    for _, __, rings in sortable:
        vector_polygons.append(VectorPolygon(role=role, rings=rings))
    return vector_polygons


def _coords_to_points(coords: List[Tuple[float, float]]) -> List[Point2D]:
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [Point2D(x=round(float(x), 4), y=round(float(y), 4)) for x, y in coords]
