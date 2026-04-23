from __future__ import annotations

import importlib.util
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .domain import optional_name


ENTITY_RE = re.compile(r"#\d+\s*=\s*([A-Z0-9_]+)\(", re.IGNORECASE)
SCHEMA_RE = re.compile(r"FILE_SCHEMA\s*\(\(\s*'([^']+)'\s*\)\)", re.IGNORECASE)


@dataclass(frozen=True)
class IfcScan:
    schema: str
    scanner: str
    entity_counts: Dict[str, int]
    project_name: str
    building_name: str
    storeys: List[tuple[str, Optional[float]]]
    space_count: int
    warnings: List[str]


def scan_ifc(path: Path) -> IfcScan:
    text = path.read_text(encoding="utf-8", errors="ignore")
    entity_counts = Counter(name.upper() for name in ENTITY_RE.findall(text))
    schema_match = SCHEMA_RE.search(text)
    schema = schema_match.group(1) if schema_match else "UNKNOWN"
    warnings: List[str] = []

    if schema == "UNKNOWN":
        warnings.append("Could not determine FILE_SCHEMA from IFC header.")

    base_scan = IfcScan(
        schema=schema,
        scanner="spf-scanner",
        entity_counts=dict(sorted(entity_counts.items())),
        project_name="Unresolved IFC Project",
        building_name="Unresolved IFC Building",
        storeys=[(name, None) for name in _generic_storey_names(entity_counts.get("IFCBUILDINGSTOREY", 0))],
        space_count=entity_counts.get("IFCSPACE", 0),
        warnings=warnings,
    )

    if not _has_ifcopenshell():
        return base_scan

    enriched = _scan_with_ifcopenshell(path, base_scan)
    return enriched if enriched is not None else base_scan


def _generic_storey_names(count: int) -> List[str]:
    if count <= 0:
        return []
    return [f"Storey {index:02d}" for index in range(1, count + 1)]


def _has_ifcopenshell() -> bool:
    return importlib.util.find_spec("ifcopenshell") is not None


def _scan_with_ifcopenshell(path: Path, fallback: IfcScan) -> Optional[IfcScan]:
    try:
        import ifcopenshell  # type: ignore

        model = ifcopenshell.open(str(path))
        project_name = "Unresolved IFC Project"
        building_name = "Unresolved IFC Building"

        projects = model.by_type("IfcProject")
        if projects:
            project_name = optional_name(getattr(projects[0], "Name", None), project_name)

        buildings = model.by_type("IfcBuilding")
        if buildings:
            building_name = optional_name(getattr(buildings[0], "Name", None), building_name)

        storeys = []
        unit_scale = 1.0
        try:
            from ifcopenshell.util.unit import calculate_unit_scale  # type: ignore

            unit_scale = float(calculate_unit_scale(model))
        except Exception:
            unit_scale = 1.0

        for index, storey in enumerate(model.by_type("IfcBuildingStorey"), start=1):
            name = optional_name(getattr(storey, "Name", None), f"Storey {index:02d}")
            elevation_m = _extract_storey_elevation_m(storey, unit_scale)
            storeys.append((name, elevation_m))

        return IfcScan(
            schema=fallback.schema,
            scanner="ifcopenshell+spf-scanner",
            entity_counts=fallback.entity_counts,
            project_name=project_name,
            building_name=building_name,
            storeys=storeys or fallback.storeys,
            space_count=len(model.by_type("IfcSpace")) or fallback.space_count,
            warnings=fallback.warnings,
        )
    except Exception as exc:
        warnings = list(fallback.warnings)
        warnings.append(f"IfcOpenShell enrichment failed: {exc!s}")
        return IfcScan(
            schema=fallback.schema,
            scanner=fallback.scanner,
            entity_counts=fallback.entity_counts,
            project_name=fallback.project_name,
            building_name=fallback.building_name,
            storeys=fallback.storeys,
            space_count=fallback.space_count,
            warnings=warnings,
        )


def _extract_storey_elevation_m(storey, unit_scale: float) -> Optional[float]:
    elevation = getattr(storey, "Elevation", None)
    if elevation is not None:
        try:
            return float(elevation) * unit_scale
        except (TypeError, ValueError):
            pass

    try:
        from ifcopenshell.util.placement import get_local_placement  # type: ignore

        matrix = get_local_placement(storey.ObjectPlacement)
        return float(matrix[2][3]) * unit_scale
    except Exception:
        return None
