from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Tuple

from .domain import FeatureAnchor2D, Point2D


FEATURE_CLASSES_DEFAULT = ("IfcDoor", "IfcStair", "IfcSpace")
_DOOR_SWING_LABEL_PREFIX = "door_swing:"


def build_feature_anchors_by_storey(
    model,
    unit_scale: float,
    get_container,
    feature_classes: Iterable[str] = FEATURE_CLASSES_DEFAULT,
) -> Dict[str, List[FeatureAnchor2D]]:
    try:
        from ifcopenshell.util.placement import get_local_placement  # type: ignore
    except Exception:
        return {}

    geom_settings = _build_world_geom_settings()

    by_storey: Dict[str, List[FeatureAnchor2D]] = {}
    for class_name in feature_classes:
        for element in model.by_type(class_name):
            storey_name = _resolve_storey_name(element, get_container)
            if not storey_name:
                continue
            anchor_data = _extract_anchor_xy(
                element,
                unit_scale,
                get_local_placement,
                geom_settings=geom_settings,
            )
            if anchor_data is None:
                continue
            anchor_x, anchor_y, matrix = anchor_data
            dir_x, dir_y = _extract_direction_xy_for_feature(
                element=element,
                class_name=class_name,
                matrix=matrix,
                unit_scale=unit_scale,
            )
            semantics = _extract_feature_semantics(element, class_name)
            width_m = _extract_element_width_m(element, class_name, unit_scale)
            anchor = FeatureAnchor2D(
                ifc_class=class_name,
                anchor=Point2D(x=round(anchor_x, 4), y=round(anchor_y, 4)),
                dir_x=round(dir_x, 6),
                dir_y=round(dir_y, 6),
                source_element=getattr(element, "GlobalId", "") or "",
                display_label=semantics.get("display_label"),
                door_handedness=semantics.get("door_handedness"),
                operation_type=semantics.get("operation_type"),
                semantic_source=semantics.get("semantic_source"),
                semantic_confidence=_optional_float(semantics.get("semantic_confidence")),
                host_element=_resolve_host_element_id(element),
                label=semantics.get("label"),
                width_m=width_m,
            )
            by_storey.setdefault(storey_name, []).append(anchor)

    for storey_name, anchors in by_storey.items():
        anchors.sort(
            key=lambda item: (
                item.ifc_class,
                item.source_element or "",
                item.anchor.y,
                item.anchor.x,
            )
        )
        by_storey[storey_name] = anchors
    return by_storey


def count_feature_anchors(anchors: Iterable[FeatureAnchor2D]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for anchor in anchors:
        counts[anchor.ifc_class] = counts.get(anchor.ifc_class, 0) + 1
    return dict(sorted(counts.items()))


def _resolve_storey_name(element, get_container) -> str:
    try:
        storey = get_container(element, ifc_class="IfcBuildingStorey")
        if storey is not None:
            name = _entity_name(storey)
            if name:
                return name
    except Exception:
        pass

    seen: set[int] = set()
    stack = [element]
    while stack:
        current = stack.pop()
        entity_id = _entity_id(current)
        if entity_id is not None and entity_id in seen:
            continue
        if entity_id is not None:
            seen.add(entity_id)
        if _is_storey(current):
            name = _entity_name(current)
            if name:
                return name

        for relation in list(getattr(current, "ContainedInStructure", []) or []):
            parent = getattr(relation, "RelatingStructure", None)
            if parent is not None:
                stack.append(parent)
        for relation in list(getattr(current, "Decomposes", []) or []):
            parent = getattr(relation, "RelatingObject", None)
            if parent is not None:
                stack.append(parent)

        # IfcDoor/IfcWindow may be linked through opening relationships.
        for relation in list(getattr(current, "FillsVoids", []) or []):
            opening = getattr(relation, "RelatingOpeningElement", None)
            if opening is not None:
                stack.append(opening)
        for relation in list(getattr(current, "VoidsElements", []) or []):
            parent = getattr(relation, "RelatingBuildingElement", None)
            if parent is not None:
                stack.append(parent)
        for relation in list(getattr(current, "HasOpenings", []) or []):
            opening = getattr(relation, "RelatedOpeningElement", None)
            if opening is not None:
                stack.append(opening)
    return ""


def _extract_anchor_xy(
    element,
    unit_scale: float,
    get_local_placement,
    geom_settings=None,
) -> Optional[Tuple[float, float, object]]:
    placement = getattr(element, "ObjectPlacement", None)
    matrix = None
    placement_x: Optional[float] = None
    placement_y: Optional[float] = None

    if placement is not None:
        try:
            matrix = get_local_placement(placement)
            placement_x = float(matrix[0][3]) * unit_scale
            placement_y = float(matrix[1][3]) * unit_scale
        except Exception:
            matrix = None

        if placement_x is None:
            try:
                relative = getattr(placement, "RelativePlacement", None)
                location = getattr(relative, "Location", None)
                coordinates = list(getattr(location, "Coordinates", []) or [])
                if len(coordinates) >= 2:
                    placement_x = float(coordinates[0]) * unit_scale
                    placement_y = float(coordinates[1]) * unit_scale
            except Exception:
                pass

    # Many IFCs leave ObjectPlacement at origin and locate the element via its
    # Representation (e.g. IfcSpace) or via decomposition children (e.g. IfcStair).
    # Fall back to a representation/decomposition centroid in those cases.
    if placement_x is None or _is_origin(placement_x, placement_y):
        centroid = _representation_centroid(element, unit_scale, geom_settings, get_local_placement)
        if centroid is not None:
            cx, cy = centroid
            return cx, cy, matrix

    if placement_x is not None:
        return placement_x, placement_y, matrix
    return None


def _is_origin(x: Optional[float], y: Optional[float], tol: float = 1e-9) -> bool:
    if x is None or y is None:
        return False
    return abs(x) < tol and abs(y) < tol


def _build_world_geom_settings():
    try:
        import ifcopenshell.geom  # type: ignore
    except Exception:
        return None
    try:
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        return settings
    except Exception:
        return None


def _representation_centroid(
    element,
    unit_scale: float,
    geom_settings,
    get_local_placement,
) -> Optional[Tuple[float, float]]:
    """World-meter XY centroid derived from geometry, with decomposition fallback."""

    # First try: aggregate child placements (cheap, no geometry build).
    # Useful for IfcStair / IfcRoof / containers whose own placement is identity
    # but whose decomposed children carry the real positions.
    child_centroid = _decomposition_centroid(element, unit_scale, get_local_placement)
    if child_centroid is not None:
        return child_centroid

    # Second try: build the shape with world-coords applied, then average verts.
    # Handles IfcSpace where the boundary lives in the swept profile.
    if geom_settings is None:
        return None
    try:
        import ifcopenshell.geom  # type: ignore
        shape = ifcopenshell.geom.create_shape(geom_settings, element)
    except Exception:
        return None
    if shape is None:
        return None
    try:
        verts = shape.geometry.verts
    except Exception:
        return None
    if not verts or len(verts) < 3:
        return None
    count = len(verts) // 3
    if count <= 0:
        return None
    sum_x = 0.0
    sum_y = 0.0
    for i in range(count):
        sum_x += float(verts[i * 3])
        sum_y += float(verts[i * 3 + 1])
    return (sum_x / count) * unit_scale, (sum_y / count) * unit_scale


def _decomposition_centroid(
    element,
    unit_scale: float,
    get_local_placement,
) -> Optional[Tuple[float, float]]:
    xs: List[float] = []
    ys: List[float] = []
    for relation in list(getattr(element, "IsDecomposedBy", []) or []):
        for child in list(getattr(relation, "RelatedObjects", []) or []):
            placement = getattr(child, "ObjectPlacement", None)
            if placement is None:
                continue
            try:
                matrix = get_local_placement(placement)
                cx = float(matrix[0][3]) * unit_scale
                cy = float(matrix[1][3]) * unit_scale
            except Exception:
                continue
            if _is_origin(cx, cy):
                continue
            xs.append(cx)
            ys.append(cy)
    if not xs or not ys:
        return None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _extract_direction_xy(matrix: object) -> Tuple[float, float]:
    if matrix is not None:
        try:
            ux = float(matrix[0][0])
            uy = float(matrix[1][0])
            ux, uy = _normalize_2d(ux, uy)
            if abs(ux) > 1.0e-9 or abs(uy) > 1.0e-9:
                return ux, uy
        except Exception:
            pass
        try:
            ux = float(matrix[0][1])
            uy = float(matrix[1][1])
            ux, uy = _normalize_2d(ux, uy)
            if abs(ux) > 1.0e-9 or abs(uy) > 1.0e-9:
                return ux, uy
        except Exception:
            pass
    return 1.0, 0.0


def _extract_direction_xy_for_feature(element, class_name: str, matrix: object, unit_scale: float) -> Tuple[float, float]:
    if class_name in ("IfcStair", "IfcStairFlight"):
        try:
            semantic_direction = _extract_stair_semantic_direction_xy(
                element=element,
                class_name=class_name,
                unit_scale=unit_scale,
            )
        except Exception:
            semantic_direction = None
        if semantic_direction is not None:
            return semantic_direction
    return _extract_direction_xy(matrix)


def _extract_stair_semantic_direction_xy(
    element,
    class_name: str,
    unit_scale: float,
) -> Optional[Tuple[float, float]]:
    semantic_direction = _extract_axis_direction_xy_from_element(element, unit_scale)
    if semantic_direction is not None:
        return semantic_direction

    if class_name == "IfcStair":
        for flight in _iter_related_stair_flights(element):
            semantic_direction = _extract_axis_direction_xy_from_element(flight, unit_scale)
            if semantic_direction is not None:
                return semantic_direction
    return None


def _extract_axis_direction_xy_from_element(element, unit_scale: float) -> Optional[Tuple[float, float]]:
    representation = getattr(element, "Representation", None)
    representations = getattr(representation, "Representations", None)
    if representations is None and representation is not None:
        representations = [representation]

    for shape_representation in _coerce_iterable(representations):
        if not _is_axis_representation(shape_representation):
            continue
        for item in _coerce_iterable(getattr(shape_representation, "Items", [])):
            semantic_direction = _extract_curve_direction_xy(item, unit_scale)
            if semantic_direction is not None:
                return semantic_direction
    return None


def _is_axis_representation(shape_representation) -> bool:
    identifier = str(getattr(shape_representation, "RepresentationIdentifier", "") or "").strip().lower()
    representation_type = str(getattr(shape_representation, "RepresentationType", "") or "").strip().lower()
    if not identifier:
        return False
    if "axis" in identifier or "path" in identifier:
        return True
    return "footprint" in identifier and "curve" in representation_type


def _extract_curve_direction_xy(curve_item, unit_scale: float) -> Optional[Tuple[float, float]]:
    points = _extract_ordered_curve_points_xy(curve_item, unit_scale, depth=0)
    if len(points) < 2:
        return None
    start_x, start_y = points[0]
    end_x, end_y = points[-1]
    ux, uy = _normalize_2d(end_x - start_x, end_y - start_y)
    if abs(ux) <= 1.0e-9 and abs(uy) <= 1.0e-9:
        return None
    return ux, uy


def _extract_ordered_curve_points_xy(curve_item, unit_scale: float, depth: int) -> List[Tuple[float, float]]:
    if curve_item is None or depth > 6:
        return []

    points_attr = _extract_points_from_points_attr(curve_item, unit_scale)
    if len(points_attr) >= 2:
        return points_attr

    trim_points = _extract_points_from_trim_attrs(curve_item, unit_scale)
    if len(trim_points) >= 2:
        return trim_points

    basis_curve = getattr(curve_item, "BasisCurve", None)
    if basis_curve is not None:
        basis_points = _extract_ordered_curve_points_xy(basis_curve, unit_scale, depth + 1)
        if len(basis_points) >= 2:
            return basis_points

    merged: List[Tuple[float, float]] = []
    for segment in _coerce_iterable(getattr(curve_item, "Segments", [])):
        parent_curve = getattr(segment, "ParentCurve", None)
        if parent_curve is None:
            parent_curve = getattr(segment, "BasisCurve", None)
        if parent_curve is None:
            parent_curve = segment
        segment_points = _extract_ordered_curve_points_xy(parent_curve, unit_scale, depth + 1)
        if not segment_points:
            continue
        if not merged:
            merged = list(segment_points)
            continue
        if _points_close_2d(merged[-1], segment_points[0]):
            merged.extend(segment_points[1:])
        else:
            merged.extend(segment_points)
    return merged


def _extract_points_from_points_attr(curve_item, unit_scale: float) -> List[Tuple[float, float]]:
    points_attr = getattr(curve_item, "Points", None)
    if points_attr is None:
        return []

    points: List[Tuple[float, float]] = []
    coord_list = getattr(points_attr, "CoordList", None)
    if coord_list is not None:
        for coordinate in _coerce_iterable(coord_list):
            point = _extract_xy_from_coordinate_seq(coordinate, unit_scale)
            if point is not None:
                points.append(point)
        return points

    for point_like in _coerce_iterable(points_attr):
        point = _extract_xy_from_point_like(point_like, unit_scale)
        if point is not None:
            points.append(point)
    return points


def _extract_points_from_trim_attrs(curve_item, unit_scale: float) -> List[Tuple[float, float]]:
    points: List[Tuple[float, float]] = []
    for attr_name in ("Trim1", "Trim2"):
        for trim_value in _coerce_iterable(getattr(curve_item, attr_name, [])):
            point = _extract_xy_from_point_like(trim_value, unit_scale)
            if point is not None:
                points.append(point)
    return points


def _extract_xy_from_point_like(value, unit_scale: float) -> Optional[Tuple[float, float]]:
    if value is None:
        return None
    coordinates = getattr(value, "Coordinates", None)
    if coordinates is not None:
        return _extract_xy_from_coordinate_seq(coordinates, unit_scale)
    if isinstance(value, (list, tuple)):
        return _extract_xy_from_coordinate_seq(value, unit_scale)
    return None


def _extract_xy_from_coordinate_seq(coordinates, unit_scale: float) -> Optional[Tuple[float, float]]:
    try:
        values = list(coordinates or [])
        if len(values) < 2:
            return None
        x = float(values[0]) * unit_scale
        y = float(values[1]) * unit_scale
    except Exception:
        return None
    return x, y


def _points_close_2d(a: Tuple[float, float], b: Tuple[float, float], tol: float = 1.0e-9) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _iter_related_stair_flights(stair) -> Iterable[object]:
    seen: set[int] = set()
    for rel_attr in ("IsDecomposedBy", "IsNestedBy", "ContainsElements"):
        for relation in _coerce_iterable(getattr(stair, rel_attr, [])):
            for related in _iter_relation_related_objects(relation):
                if not _is_ifc_class(related, "IfcStairFlight"):
                    continue
                entity_id = _entity_id(related)
                if entity_id is not None:
                    if entity_id in seen:
                        continue
                    seen.add(entity_id)
                yield related


def _iter_relation_related_objects(relation) -> Iterable[object]:
    for attr_name in ("RelatedObjects", "RelatedElements"):
        for related in _coerce_iterable(getattr(relation, attr_name, [])):
            if related is not None:
                yield related


def _is_ifc_class(entity, class_name: str) -> bool:
    try:
        value = entity.is_a(class_name)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value == class_name
    except TypeError:
        pass
    except Exception:
        return False

    try:
        value = entity.is_a()
        return str(value or "") == class_name
    except Exception:
        return False


def _extract_label(element, class_name: str) -> Optional[str]:
    return _extract_feature_semantics(element, class_name).get("label")


def _extract_feature_semantics(element, class_name: str) -> Dict[str, object]:
    if class_name == "IfcSpace":
        label = _extract_space_semantic_label(element)
        if label is None:
            return {}
        return {
            "display_label": label,
            "semantic_source": "ifc_space_label",
            "semantic_confidence": 0.85,
            "label": label,
        }

    if class_name == "IfcDoor":
        candidates = [
            ("OperationType", getattr(element, "OperationType", None)),
            ("UserDefinedOperationType", getattr(element, "UserDefinedOperationType", None)),
            ("PredefinedType", getattr(element, "PredefinedType", None)),
            ("ObjectType", getattr(element, "ObjectType", None)),
            ("Name", getattr(element, "Name", None)),
        ]
        candidates.extend(
            (f"property:{name}", value)
            for name, value in _extract_semantic_property_pairs(
                element,
                candidate_names=(
                    "OperationType",
                    "DoorOperationType",
                    "HingeSide",
                    "Handing",
                    "DoorHanding",
                    "SwingDirection",
                ),
            )
        )
        semantic_hint = None
        semantic_source = None
        operation_type = None
        for source, value in candidates:
            text = _value_to_text(value)
            if text and operation_type is None and "operation" in source.lower():
                operation_type = text
            semantic_hint = _extract_door_swing_handedness(value)
            if semantic_hint is not None:
                semantic_source = source
                break
        if semantic_hint is not None:
            return {
                "door_handedness": semantic_hint,
                "operation_type": operation_type,
                "semantic_source": semantic_source or "door_handedness",
                "semantic_confidence": 0.75,
                "label": f"{_DOOR_SWING_LABEL_PREFIX}{semantic_hint}",
            }
    return {}


def _extract_space_semantic_label(element) -> Optional[str]:
    attr_name = _first_nonempty_label(
        getattr(element, attr, None)
        for attr in ("LongName", "Name", "ObjectType")
    )
    attr_number = _first_nonempty_label(
        getattr(element, attr, None)
        for attr in ("Number", "Reference", "Tag")
    )
    prop_name = _first_nonempty_label(
        _extract_semantic_property_strings(
            element,
            candidate_names=("LongName", "Name", "RoomName", "SpaceName", "Label"),
        )
    )
    prop_number = _first_nonempty_label(
        _extract_semantic_property_strings(
            element,
            candidate_names=("Number", "Reference", "RoomNumber", "SpaceNumber", "Tag"),
        )
    )
    name = attr_name or prop_name
    number = attr_number or prop_number
    if number and name:
        combined = f"{number} {name}".strip()
        return combined[:48]
    if name:
        return name[:48]
    if number:
        return number[:48]
    return None


def _first_nonempty_label(values: Iterable[object]) -> Optional[str]:
    for value in values:
        text = _value_to_text(value)
        if text:
            return text
    return None


def _extract_semantic_property_strings(
    element,
    *,
    candidate_names: Iterable[str],
) -> List[str]:
    return [value for _name, value in _extract_semantic_property_pairs(element, candidate_names=candidate_names)]


def _extract_semantic_property_pairs(
    element,
    *,
    candidate_names: Iterable[str],
) -> List[Tuple[str, str]]:
    wanted = {_normalize_property_name(name) for name in candidate_names}
    values: List[Tuple[str, str]] = []
    for relation in _coerce_iterable(getattr(element, "IsDefinedBy", [])):
        prop_set = getattr(relation, "RelatingPropertyDefinition", None)
        if prop_set is None:
            continue
        for prop in _coerce_iterable(getattr(prop_set, "HasProperties", [])):
            prop_name = _normalize_property_name(getattr(prop, "Name", ""))
            if not prop_name or prop_name not in wanted:
                continue
            property_values = []
            property_values.extend(_coerce_iterable(getattr(prop, "EnumerationValues", [])))
            property_values.extend(_coerce_iterable(getattr(prop, "ListValues", [])))
            property_values.extend(
                [
                    getattr(prop, "NominalValue", None),
                    getattr(prop, "UpperBoundValue", None),
                    getattr(prop, "LowerBoundValue", None),
                ]
            )
            text = _first_nonempty_label(property_values)
            if text:
                values.append((str(getattr(prop, "Name", "") or ""), text))
    return values


def _resolve_host_element_id(element) -> Optional[str]:
    for relation in _coerce_iterable(getattr(element, "FillsVoids", [])):
        opening = getattr(relation, "RelatingOpeningElement", None)
        for void_relation in _coerce_iterable(getattr(opening, "VoidsElements", [])):
            host = getattr(void_relation, "RelatingBuildingElement", None)
            global_id = getattr(host, "GlobalId", None)
            if global_id:
                return str(global_id)
    return None


def _optional_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _normalize_property_name(value: object) -> str:
    text = str(value or "").strip().lower()
    chars = []
    for char in text:
        if char.isalnum():
            chars.append(char)
    return "".join(chars)


def _value_to_text(value: object) -> Optional[str]:
    if value is None:
        return None
    wrapped = getattr(value, "wrappedValue", None)
    if wrapped is not None:
        value = wrapped
    text = str(value).strip()
    return text if text else None


def _extract_door_swing_handedness(value: object) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = "".join(ch if ch.isalpha() else " " for ch in text.upper())
    tokens = [token for token in normalized.split() if token]
    joined = "".join(tokens)
    left_tokens = {"LEFT", "LH", "LEFTHAND", "HANDLEFT", "HINGELEFT"}
    right_tokens = {"RIGHT", "RH", "RIGHTHAND", "HANDRIGHT", "HINGERIGHT"}
    has_left = any(token in left_tokens for token in tokens) or "SWINGLEFT" in joined
    has_right = any(token in right_tokens for token in tokens) or "SWINGRIGHT" in joined
    if has_left and not has_right:
        return "left"
    if has_right and not has_left:
        return "right"
    return None


def _normalize_2d(x: float, y: float) -> Tuple[float, float]:
    length = math.hypot(x, y)
    if length <= 1.0e-12:
        return 0.0, 0.0
    return x / length, y / length


def _coerce_iterable(value) -> List[object]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    try:
        return list(value)
    except TypeError:
        return [value]
    except Exception:
        return []


def _entity_name(entity) -> str:
    return str(getattr(entity, "Name", "") or "").strip()


def _entity_id(entity) -> Optional[int]:
    try:
        return int(entity.id())
    except Exception:
        return None


def _is_storey(entity) -> bool:
    try:
        return bool(entity.is_a("IfcBuildingStorey"))
    except Exception:
        return False


def _extract_element_width_m(element, class_name: str, unit_scale: float) -> Optional[float]:
    """Return OverallWidth (doors/windows) or None when unavailable."""
    if class_name not in ("IfcDoor", "IfcWindow"):
        return None
    # IFC standard attributes OverallWidth / OverallHeight
    for attr in ("OverallWidth", "Width"):
        try:
            value = getattr(element, attr, None)
            if value is not None:
                width = float(value) * unit_scale
                if 0.1 < width < 20.0:   # sanity: between 10 cm and 20 m
                    return round(width, 4)
        except Exception:
            pass
    # Fall back to property sets (Pset_DoorCommon, Pset_WindowCommon)
    try:
        for definition in _coerce_iterable(getattr(element, "IsDefinedBy", [])):
            relating = getattr(definition, "RelatingPropertyDefinition", None)
            if relating is None:
                continue
            pset_name = str(getattr(relating, "Name", "") or "")
            if "Common" not in pset_name and "Door" not in pset_name and "Window" not in pset_name:
                continue
            for prop in _coerce_iterable(getattr(relating, "HasProperties", [])):
                prop_name = str(getattr(prop, "Name", "") or "").lower()
                if prop_name in ("overallwidth", "width", "leafwidth"):
                    nom = getattr(prop, "NominalValue", None)
                    if nom is not None:
                        width = float(getattr(nom, "wrappedValue", nom)) * unit_scale
                        if 0.1 < width < 20.0:
                            return round(width, 4)
    except Exception:
        pass
    return None
