from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from .domain import ScheduleRow, ScheduleSheet


@dataclass(frozen=True)
class _ScheduleFamily:
    category: str
    title: str
    label_header: str
    mode: str
    classes: tuple[str, ...]
    notes: tuple[str, ...]


SCHEDULE_FAMILIES = (
    _ScheduleFamily(
        category="space_schedule",
        title="Space Schedule",
        label_header="Space / Label",
        mode="inventory",
        classes=("IfcSpace",),
        notes=(
            "One row per grouped space label and storey when IfcSpace data is present.",
            "Labels resolve from LongName, then Name, then GlobalId.",
        ),
    ),
    _ScheduleFamily(
        category="opening_schedule",
        title="Opening Type Schedule",
        label_header="Type / Label",
        mode="type",
        classes=("IfcDoor", "IfcWindow"),
        notes=(
            "Grouped by IFC class, resolved type label, and containing storey.",
            "Type labels resolve from IfcType first, then ObjectType, then Name.",
        ),
    ),
    _ScheduleFamily(
        category="circulation_schedule",
        title="Circulation Schedule",
        label_header="Type / Label",
        mode="type",
        classes=("IfcStair", "IfcRamp"),
        notes=(
            "Grouped by IFC class, resolved type label, and containing storey.",
            "This schedule appears only when stairs or ramps are present in the IFC.",
        ),
    ),
    _ScheduleFamily(
        category="element_type_schedule",
        title="Element Type Schedule",
        label_header="Type / Label",
        mode="type",
        classes=("IfcColumn", "IfcBeam", "IfcMember", "IfcSlab"),
        notes=(
            "Grouped by IFC class, resolved type label, and containing storey.",
            "This schedule is intentionally generic so it can absorb richer professional models without code changes.",
        ),
    ),
)


def extract_schedule_sheets(
    ifc_path: Path,
    sheet_prefix: str,
    start_sheet_number: int = 601,
    rows_per_sheet: int = 24,
) -> List[ScheduleSheet]:
    try:
        import ifcopenshell  # type: ignore
        from ifcopenshell.util.element import get_container, get_type  # type: ignore
    except Exception:
        return []

    model = ifcopenshell.open(str(ifc_path))
    sheets: List[ScheduleSheet] = []
    next_sheet_number = start_sheet_number

    for family in SCHEDULE_FAMILIES:
        rows = _extract_family_rows(model, family, get_container, get_type)
        if not rows:
            continue

        chunks = list(_chunk(rows, rows_per_sheet))
        for page_index, chunk in enumerate(chunks, start=1):
            sheet_id = f"{sheet_prefix}-{next_sheet_number:03d}"
            next_sheet_number += 1
            total_pages = len(chunks)
            page_suffix = f" ({page_index}/{total_pages})" if total_pages > 1 else ""
            sheets.append(
                ScheduleSheet(
                    schedule_id=f"{family.category}_{page_index:02d}",
                    sheet_id=sheet_id,
                    title=f"{family.title}{page_suffix}",
                    category=family.category,
                    label_header=family.label_header,
                    rows=chunk,
                    notes=list(family.notes),
                )
            )

    return sheets


def _extract_family_rows(model, family: _ScheduleFamily, get_container, get_type) -> List[ScheduleRow]:
    if family.mode == "inventory":
        return _extract_inventory_rows(model, family, get_container)
    return _extract_type_rows(model, family, get_container, get_type)


def _extract_inventory_rows(model, family: _ScheduleFamily, get_container) -> List[ScheduleRow]:
    counts = Counter()
    for class_name in family.classes:
        for element in model.by_type(class_name):
            label = _resolved_inventory_label(element, class_name)
            storey_name = _resolved_storey_name(element, get_container)
            counts[(class_name, label, storey_name)] += 1

    rows = [
        ScheduleRow(ifc_class=ifc_class, label=label, storey_name=storey_name, count=count)
        for (ifc_class, label, storey_name), count in counts.items()
    ]
    rows.sort(key=lambda row: (row.storey_name, row.ifc_class, row.label, row.count))
    return rows


def _extract_type_rows(model, family: _ScheduleFamily, get_container, get_type) -> List[ScheduleRow]:
    counts = Counter()
    for class_name in family.classes:
        for element in model.by_type(class_name):
            label = _resolved_type_label(element, class_name, get_type)
            storey_name = _resolved_storey_name(element, get_container)
            counts[(class_name, label, storey_name)] += 1

    rows = [
        ScheduleRow(ifc_class=ifc_class, label=label, storey_name=storey_name, count=count)
        for (ifc_class, label, storey_name), count in counts.items()
    ]
    rows.sort(key=lambda row: (row.storey_name, row.ifc_class, row.label, row.count))
    return rows


def _resolved_inventory_label(element, class_name: str) -> str:
    for attr in ("LongName", "Name", "ObjectType"):
        value = getattr(element, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return getattr(element, "GlobalId", None) or class_name


def _resolved_type_label(element, class_name: str, get_type) -> str:
    resolved_type = None
    try:
        resolved_type = get_type(element)
    except Exception:
        resolved_type = None

    candidates = (
        getattr(resolved_type, "Name", None) if resolved_type is not None else None,
        getattr(resolved_type, "ObjectType", None) if resolved_type is not None else None,
        getattr(element, "ObjectType", None),
        getattr(element, "Name", None),
        getattr(element, "GlobalId", None),
    )
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return class_name


def _resolved_storey_name(element, get_container) -> str:
    try:
        container = get_container(element)
    except Exception:
        container = None
    storey_name = getattr(container, "Name", None) if container is not None else None
    if isinstance(storey_name, str) and storey_name.strip():
        return storey_name.strip()
    return "Unassigned"


def _chunk(rows: List[ScheduleRow], size: int) -> Iterable[List[ScheduleRow]]:
    for index in range(0, len(rows), size):
        yield rows[index : index + size]
