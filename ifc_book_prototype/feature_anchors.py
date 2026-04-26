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

    by_storey: Dict[str, List[FeatureAnchor2D]] = {}
    for class_name in feature_classes:
        for element in model.by_type(class_name):
            storey_name = _resolve_storey_name(element, get_container)
            if not storey_name:
                continue
            anchor_data = _extract_anchor_xy(element, unit_scale, get_local_placement)
            if anchor_data is None:
                continue
            anchor_x, anchor_y, matrix = anchor_data
            dir_x, dir_y = _extract_direction_xy_for_feature(
                element=element,
                class_name=class_name,
                matrix=matrix,
                unit_scale=unit_scale,
            )
            label = _extract_label(element, class_name)
            anchor = FeatureAnchor2D(
                ifc_class=class_name,
                anchor=Point2D(x=round(anchor_x, 4), y=round(anchor_y, 4)),
                dir_x=round(dir_x, 6),
                dir_y=round(dir_y, 6),
                source_element=getattr(element, "GlobalId", "") or "",
                label=label,
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


def _extract_anchor_xy(element, unit_scale: float, get_local_placement) -> Optional[Tuple[float, float, object]]:
    placement = getattr(element, "ObjectPlacement", None)
    if placement is None:
        return None
    try:
        matrix = get_local_placement(placement)
        x = float(matrix[0][3]) * unit_scale
        y = float(matrix[1][3]) * unit_scale
        return x, y, matrix
    except Exception:
        pass

    try:
        relative = getattr(placement, "RelativePlacement", None)
        location = getattr(relative, "Location", None)
        coordinates = list(getattr(location, "Coordinates", []) or [])
        if len(coordinates) >= 2:
            x = float(coordinates[0]) * unit_scale
            y = float(coordinates[1]) * unit_scale
            return x, y, None
    except Exception:
        pass
    return None


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
    if class_name == "IfcSpace":
        return _extract_space_semantic_label(element)

    if class_name == "IfcDoor":
        candidates = [
            getattr(element, "OperationType", None),
            getattr(element, "UserDefinedOperationType", None),
            getattr(element, "PredefinedType", None),
            getattr(element, "ObjectType", None),
            getattr(element, "Name", None),
        ]
        candidates.extend(
            _extract_semantic_property_strings(
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
        for value in candidates:
            semantic_hint = _extract_door_swing_handedness(value)
            if semantic_hint is not None:
                break
        if semantic_hint is not None:
            return f"{_DOOR_SWING_LABEL_PREFIX}{semantic_hint}"
    return None


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
    wanted = {_normalize_property_name(name) for name in candidate_names}
    values: List[str] = []
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
                values.append(text)
    return values


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
