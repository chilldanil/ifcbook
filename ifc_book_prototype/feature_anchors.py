from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Tuple

from .domain import FeatureAnchor2D, Point2D


FEATURE_CLASSES_DEFAULT = ("IfcDoor", "IfcStair", "IfcSpace")


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
            dir_x, dir_y = _extract_direction_xy(matrix)
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


def _extract_label(element, class_name: str) -> Optional[str]:
    if class_name != "IfcSpace":
        return None
    for attr in ("LongName", "Name"):
        value = getattr(element, attr, None)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text[:48]
    return None


def _normalize_2d(x: float, y: float) -> Tuple[float, float]:
    length = math.hypot(x, y)
    if length <= 1.0e-12:
        return 0.0, 0.0
    return x / length, y / length


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
