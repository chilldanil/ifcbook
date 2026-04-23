from __future__ import annotations

from html import escape
from typing import Iterable, List, Tuple

from .domain import (
    Bounds2D,
    GeometrySummary,
    NormalizedModel,
    PlannedView,
    ScheduleSheet,
    StyleProfile,
    VectorPath,
    VectorPolygon,
)


PRIMARY_CUT_CLASSES = frozenset({"IfcWall", "IfcSlab"})


def render_cover_svg(model: NormalizedModel, profile: StyleProfile, job_id: str, input_sha256: str) -> str:
    lines = [
        ("Project", model.project_name),
        ("Building", model.building_name),
        ("Schema", model.schema),
        ("Style Profile", profile.profile_id),
        ("Job ID", job_id),
        ("Input SHA256", input_sha256[:20] + "..."),
        ("Storeys", str(len(model.storeys))),
        ("Spaces", str(model.space_count)),
    ]
    body = _info_lines(lines, start_y=58.0)
    title = "Prototype Architectural Drawing Book"
    subtitle = "Research-to-implementation MVP scaffold"
    return _wrap_sheet(
        title=title,
        sheet_id=profile.cover_sheet_id,
        subtitle=subtitle,
        body=body,
        profile=profile,
    )


def render_index_svg(sheets: Iterable[Tuple[str, str]], profile: StyleProfile) -> str:
    rows = []
    y = 40.0
    for sheet_id, title in sheets:
        rows.append(_text(20.0, y, f"{sheet_id}", 5.0, weight="700"))
        rows.append(_text(50.0, y, title, 4.0))
        y += 9.0
    body = "\n".join(rows)
    return _wrap_sheet(
        title="Drawing Index",
        sheet_id=profile.index_sheet_id,
        subtitle="Generated deterministically from the planned sheet list",
        body=body,
        profile=profile,
    )


def render_schedule_svg(schedule: ScheduleSheet, profile: StyleProfile) -> str:
    table_x = 16.0
    table_y = 38.0
    row_height = 8.0
    class_x = table_x + 2.0
    label_x = table_x + 38.0
    storey_x = table_x + 127.0
    count_x = table_x + 171.0
    table_width = 178.0
    table_height = row_height * (len(schedule.rows) + 1)

    rows = [
        _text(table_x, table_y - 5.0, "Deterministic IFC schedule extraction", 3.5, fill="#334155"),
        f'<rect x="{table_x}" y="{table_y}" width="{table_width}" height="{table_height}" fill="#fffefb" stroke="#0f172a" stroke-width="0.25"/>',
    ]

    for divider_x in (table_x + 34.0, table_x + 123.0, table_x + 167.0):
        rows.append(
            f'<line x1="{divider_x}" y1="{table_y}" x2="{divider_x}" y2="{table_y + table_height}" stroke="#94a3b8" stroke-width="0.18"/>'
        )

    for row_index in range(1, len(schedule.rows) + 1):
        y = table_y + row_index * row_height
        rows.append(f'<line x1="{table_x}" y1="{y}" x2="{table_x + table_width}" y2="{y}" stroke="#cbd5e1" stroke-width="0.18"/>')

    rows.extend(
        [
            _text(class_x, table_y + 5.5, "Class", 3.8, weight="700"),
            _text(label_x, table_y + 5.5, schedule.label_header, 3.8, weight="700"),
            _text(storey_x, table_y + 5.5, "Storey", 3.8, weight="700"),
            _text(count_x, table_y + 5.5, "Count", 3.8, weight="700"),
        ]
    )

    for index, row in enumerate(schedule.rows, start=1):
        baseline = table_y + index * row_height + 5.3
        rows.extend(
            [
                _text(class_x, baseline, row.ifc_class.replace("Ifc", ""), 3.4),
                _text(label_x, baseline, _truncate(row.label, 42), 3.4),
                _text(storey_x, baseline, _truncate(row.storey_name, 18), 3.4),
                _text(count_x, baseline, str(row.count), 3.4, weight="700"),
            ]
        )

    note_y = table_y + table_height + 12.0
    notes = [_text(16.0, note_y, "Notes", 4.2, weight="700")]
    for offset, note in enumerate(schedule.notes, start=1):
        notes.append(_text(16.0, note_y + offset * 6.0, f"- {note}", 3.4))

    return _wrap_sheet(
        title=schedule.title,
        sheet_id=schedule.sheet_id,
        subtitle="Capability-driven schedule planning from IFC content",
        body="\n".join(rows + notes),
        profile=profile,
    )


def render_view_svg(
    model: NormalizedModel,
    view: PlannedView,
    geometry: GeometrySummary,
    profile: StyleProfile,
) -> str:
    drawing = _plan_drawing(geometry, profile, x=20.0, y=38.0, width=170.0, height=150.0)
    info_lines = [
        ("Storey", view.storey_name),
        ("Storey elev. (m)", _format_optional_float(view.storey_elevation_m)),
        ("Cut plane (m)", f"{view.cut_plane_m:.2f}"),
        ("Geometry backend", geometry.backend),
        ("Source elements", str(geometry.source_elements)),
        ("Line paths", str(geometry.path_count)),
        ("Cut classes", _format_class_counts(geometry.cut_candidates)),
        ("Proj. classes", _format_class_counts(geometry.projection_candidates)),
    ]
    detail = _info_lines(info_lines, start_y=205.0)
    note_y = 257.0
    notes = [_text(20.0, note_y, "Notes", 4.4, weight="700")]
    for index, note in enumerate(geometry.notes, start=1):
        notes.append(_text(20.0, note_y + index * 6.0, f"- {note}", 3.5))
    return _wrap_sheet(
        title=view.title,
        sheet_id=view.sheet_id,
        subtitle="Real IFC-driven floor-plan linework prototype",
        body="\n".join([drawing, detail, "\n".join(notes)]),
        profile=profile,
    )


def _wrap_sheet(title: str, sheet_id: str, subtitle: str, body: str, profile: StyleProfile) -> str:
    width = profile.page.width_mm
    height = profile.page.height_mm
    margin = profile.page.margin_mm
    title_block_height = profile.page.title_block_height_mm
    drawing_bottom = height - margin - title_block_height
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" '
        f'viewBox="0 0 {width} {height}">\n'
        f'  <rect x="0" y="0" width="{width}" height="{height}" fill="#faf8f2"/>\n'
        f'  <rect x="{margin}" y="{margin}" width="{width - 2 * margin}" '
        f'height="{drawing_bottom - margin}" fill="#fffefb" stroke="#0f172a" stroke-width="0.35"/>\n'
        f'  <rect x="{margin}" y="{drawing_bottom}" width="{width - 2 * margin}" '
        f'height="{title_block_height}" fill="#f2efe6" stroke="#0f172a" stroke-width="0.35"/>\n'
        f'  {_text(margin + 4.0, 18.0, title, 7.0, weight="700")}\n'
        f'  {_text(margin + 4.0, 25.0, subtitle, 3.5, fill="#334155")}\n'
        f'  {body}\n'
        f'  {_text(margin + 4.0, drawing_bottom + 7.0, sheet_id, 6.0, weight="700")}\n'
        f'  {_text(margin + 28.0, drawing_bottom + 7.0, title, 4.5)}\n'
        f'  {_text(width - margin - 32.0, drawing_bottom + 7.0, profile.profile_id, 3.8)}\n'
        f'  {_text(width - margin - 32.0, drawing_bottom + 13.0, "Generated by ifc-book-prototype", 3.2, fill="#334155")}\n'
        f'</svg>\n'
    )


def _info_lines(lines: Iterable[Tuple[str, str]], start_y: float) -> str:
    rows: List[str] = []
    y = start_y
    for label, value in lines:
        rows.append(_text(20.0, y, label, 4.0, weight="700"))
        rows.append(_text(58.0, y, value, 4.0))
        y += 8.0
    return "\n".join(rows)


def _plan_drawing(geometry: GeometrySummary, profile: StyleProfile, x: float, y: float, width: float, height: float) -> str:
    if geometry.bounds is not None and geometry.paths:
        return _plan_linework(geometry, profile, x, y, width, height)

    if geometry.bounds is None or not geometry.polygons:
        return "\n".join(
            [
                _text(x, y, "No plan geometry was generated for this view.", 4.0),
                _text(x, y + 8.0, "The sheet remains deterministic and the backend can be replaced without changing the pipeline.", 3.5),
            ]
        )

    bounds = geometry.bounds
    transform = _build_transform(bounds, x, y, width, height)
    drawing = [
        _text(x, y - 5.0, "Plan geometry from IFC triangulation projected to sheet space", 3.5, fill="#334155"),
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#fffefb" stroke="#cbd5e1" stroke-width="0.25"/>',
    ]
    cut_polygons = [polygon for polygon in geometry.polygons if polygon.role == "cut"]
    projection_polygons = [polygon for polygon in geometry.polygons if polygon.role == "projection"]
    for polygon in projection_polygons:
        drawing.append(_polygon_path(polygon, transform, stroke="#334155", fill="none", stroke_width=0.18, dash="1.3 1.3"))
    for polygon in cut_polygons:
        drawing.append(_polygon_path(polygon, transform, stroke="#5c2d18", fill="#d6b39b", stroke_width=0.28))

    drawing.append(_text(x + 2.0, y + height - 3.0, _format_bounds(bounds), 2.7, fill="#475569"))
    return "\n".join(drawing)


def _plan_linework(geometry: GeometrySummary, profile: StyleProfile, x: float, y: float, width: float, height: float) -> str:
    bounds = geometry.bounds
    assert bounds is not None
    transform = _build_transform(bounds, x, y, width, height)
    drawing = [
        _text(x, y - 5.0, "Plan linework from IfcOpenShell floorplan serializer", 3.5, fill="#334155"),
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#fffefb" stroke="#cbd5e1" stroke-width="0.25"/>',
    ]
    for path in [path for path in geometry.paths if path.role == "projection"]:
        drawing.append(
            _vector_path_path(
                path,
                transform,
                stroke="#475569",
                stroke_width=_lineweight_for_path(path, profile, "projection"),
            )
        )
    for path in [path for path in geometry.paths if path.role == "cut"]:
        drawing.append(
            _vector_path_path(
                path,
                transform,
                stroke="#111827",
                stroke_width=_lineweight_for_path(path, profile, "cut"),
            )
        )
    drawing.append(_text(x + 2.0, y + height - 3.0, _format_bounds(bounds), 2.7, fill="#475569"))
    return "\n".join(drawing)


def _build_transform(bounds: Bounds2D, x: float, y: float, width: float, height: float):
    world_width = max(bounds.max_x - bounds.min_x, 1e-6)
    world_height = max(bounds.max_y - bounds.min_y, 1e-6)
    padding = 4.0
    usable_width = width - padding * 2.0
    usable_height = height - padding * 2.0
    scale = min(usable_width / world_width, usable_height / world_height)
    x_offset = x + padding + (usable_width - world_width * scale) / 2.0
    y_offset = y + padding + (usable_height - world_height * scale) / 2.0

    def transform(px: float, py: float) -> Tuple[float, float]:
        sx = x_offset + (px - bounds.min_x) * scale
        sy = y_offset + (bounds.max_y - py) * scale
        return round(sx, 3), round(sy, 3)

    return transform


def _polygon_path(
    polygon: VectorPolygon,
    transform,
    stroke: str,
    fill: str,
    stroke_width: float,
    dash: str | None = None,
) -> str:
    commands: List[str] = []
    for ring in polygon.rings:
        if not ring:
            continue
        start_x, start_y = transform(ring[0].x, ring[0].y)
        commands.append(f"M {start_x} {start_y}")
        for point in ring[1:]:
            x, y = transform(point.x, point.y)
            commands.append(f"L {x} {y}")
        commands.append("Z")
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<path d="{" ".join(commands)}" fill="{fill}" fill-rule="evenodd" '
        f'stroke="{stroke}" stroke-width="{stroke_width}"{dash_attr}/>'
    )


def _vector_path_path(path: VectorPath, transform, stroke: str, stroke_width: float) -> str:
    commands: List[str] = []
    start_x, start_y = transform(path.points[0].x, path.points[0].y)
    commands.append(f"M {start_x} {start_y}")
    for point in path.points[1:]:
        x, y = transform(point.x, point.y)
        commands.append(f"L {x} {y}")
    if path.closed:
        commands.append("Z")
    return (
        f'<path d="{" ".join(commands)}" fill="none" '
        f'stroke="{stroke}" stroke-width="{stroke_width}" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
    )


def _lineweight_for_path(path: VectorPath, profile: StyleProfile, role: str) -> float:
    if role == "projection":
        return profile.lineweights_mm.get("projected", 0.18)
    if path.ifc_class in PRIMARY_CUT_CLASSES:
        return profile.lineweights_mm.get("cut_primary", 0.35)
    return profile.lineweights_mm.get("cut_secondary", 0.25)


def _format_class_counts(counts) -> str:
    items = [f"{name.replace('Ifc', '')}:{value}" for name, value in counts.items() if value > 0]
    return ", ".join(items[:5]) + (" ..." if len(items) > 5 else "") if items else "none"


def _format_optional_float(value) -> str:
    return "-" if value is None else f"{value:.2f}"


def _format_bounds(bounds: Bounds2D) -> str:
    width = bounds.max_x - bounds.min_x
    height = bounds.max_y - bounds.min_y
    return f"world extents {width:.2f}m x {height:.2f}m"


def _truncate(value: str, length: int) -> str:
    if len(value) <= length:
        return value
    if length <= 3:
        return value[:length]
    return value[: max(0, length - 3)].rstrip() + "..."


def _text(x: float, y: float, value: str, size: float, weight: str = "400", fill: str = "#0f172a") -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" font-family="Helvetica, Arial, sans-serif" '
        f'font-weight="{weight}" fill="{fill}">{escape(value)}</text>'
    )
