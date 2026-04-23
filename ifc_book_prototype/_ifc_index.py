"""Shared IFC indexing helpers used by every geometry backend.

Both the serializer-based backend and the OCCT-based backend need to map
IFC elements to storeys with identical, deterministic ordering. Extracting
the helpers here keeps the two backends in lockstep — there is exactly one
source of truth for which elements feed which storey view.
"""
from __future__ import annotations

from typing import Dict, Iterable, List


def build_storey_elevations(model, unit_scale: float) -> Dict[str, float]:
    """Storey-name → elevation in metres."""
    elevations: Dict[str, float] = {}
    for storey in model.by_type("IfcBuildingStorey"):
        name = (getattr(storey, "Name", None) or "").strip()
        if not name:
            continue
        elevation = getattr(storey, "Elevation", None)
        if elevation is not None:
            elevations[name] = float(elevation) * unit_scale
    return elevations


def index_elements_by_storey(
    model,
    included_classes: Iterable[str],
    get_container,
) -> Dict[str, List[object]]:
    """Storey-name → deterministically sorted element list."""
    by_storey: Dict[str, List[object]] = {}
    for class_name in included_classes:
        for element in model.by_type(class_name):
            container = get_container(element)
            storey_name = (getattr(container, "Name", None) or "").strip() if container else ""
            if not storey_name:
                continue
            by_storey.setdefault(storey_name, []).append(element)
    for elements in by_storey.values():
        # Identical key to the inline sorts inside IfcSerializerPlanBackend /
        # IfcMeshPlanBackend so refactoring later does not drift hashes.
        elements.sort(
            key=lambda element: (
                element.is_a(),
                getattr(element, "GlobalId", ""),
                element.id(),
            )
        )
    return by_storey
