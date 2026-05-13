from __future__ import annotations

import math
from html import escape
from typing import Dict, Iterable, List, Tuple

from .domain import (
    Bounds2D,
    ELEVATION_VIEW_KINDS,
    FeatureOverlayRule,
    GeometrySummary,
    LineKind,
    LineweightClass,
    NormalizedModel,
    PlannedView,
    Point2D,
    ScheduleSheet,
    StyleProfile,
    TypedLine2D,
    VectorPath,
    VectorPolygon,
    typed_line_sort_key,
)


PRIMARY_CUT_CLASSES = frozenset({"IfcWall", "IfcSlab"})

# --- Dimension line style constants ---
_DIM_COLOR = "#1e3a5f"
_DIM_STROKE_W = 0.18
_DIM_EXT_STROKE_W = 0.15
_DIM_TICK_HALF = 1.6   # half-length of oblique (45°) tick mark
_DIM_GAP = 5.0         # mm from drawing frame edge to dim line
_DIM_EXT_OVERSHOOT = 1.5  # extension line protrudes this far past the dim line
_DIM_TEXT_SIZE = 2.8
_DIM_BG = "#faf8f2"    # label background matches page colour


def _dim_h(
    sx1: float,
    sx2: float,
    dim_y: float,
    label: str,
    ext_from_y: float,
) -> List[str]:
    """Horizontal dimension line with oblique tick marks and centred label."""
    els: List[str] = []
    ext_to_y = dim_y + _DIM_EXT_OVERSHOOT
    for sx in (sx1, sx2):
        els.append(
            f'<line x1="{sx:.3f}" y1="{ext_from_y:.3f}" x2="{sx:.3f}" y2="{ext_to_y:.3f}" '
            f'stroke="{_DIM_COLOR}" stroke-width="{_DIM_EXT_STROKE_W}"/>'
        )
    els.append(
        f'<line x1="{sx1:.3f}" y1="{dim_y:.3f}" x2="{sx2:.3f}" y2="{dim_y:.3f}" '
        f'stroke="{_DIM_COLOR}" stroke-width="{_DIM_STROKE_W}"/>'
    )
    t = _DIM_TICK_HALF
    for sx in (sx1, sx2):
        els.append(
            f'<line x1="{sx - t:.3f}" y1="{dim_y + t:.3f}" x2="{sx + t:.3f}" y2="{dim_y - t:.3f}" '
            f'stroke="{_DIM_COLOR}" stroke-width="{_DIM_STROKE_W}"/>'
        )
    mid_x = (sx1 + sx2) / 2.0
    char_w = _DIM_TEXT_SIZE * 0.55
    bg_w = max(8.0, len(label) * char_w + 2.0)
    bg_h = _DIM_TEXT_SIZE + 1.2
    els.append(
        f'<rect x="{mid_x - bg_w / 2:.3f}" y="{dim_y - bg_h:.3f}" '
        f'width="{bg_w:.3f}" height="{bg_h:.3f}" fill="{_DIM_BG}"/>'
    )
    els.append(
        f'<text x="{mid_x:.3f}" y="{dim_y - 0.6:.3f}" font-size="{_DIM_TEXT_SIZE}" '
        f'font-family="Helvetica, Arial, sans-serif" font-weight="400" '
        f'fill="{_DIM_COLOR}" text-anchor="middle">{escape(label)}</text>'
    )
    return els


def _dim_v(
    sy1: float,
    sy2: float,
    dim_x: float,
    label: str,
    ext_from_x: float,
) -> List[str]:
    """Vertical dimension line with oblique tick marks and rotated label."""
    els: List[str] = []
    ext_to_x = dim_x + _DIM_EXT_OVERSHOOT
    for sy in (sy1, sy2):
        els.append(
            f'<line x1="{ext_from_x:.3f}" y1="{sy:.3f}" x2="{ext_to_x:.3f}" y2="{sy:.3f}" '
            f'stroke="{_DIM_COLOR}" stroke-width="{_DIM_EXT_STROKE_W}"/>'
        )
    els.append(
        f'<line x1="{dim_x:.3f}" y1="{sy1:.3f}" x2="{dim_x:.3f}" y2="{sy2:.3f}" '
        f'stroke="{_DIM_COLOR}" stroke-width="{_DIM_STROKE_W}"/>'
    )
    t = _DIM_TICK_HALF
    for sy in (sy1, sy2):
        els.append(
            f'<line x1="{dim_x - t:.3f}" y1="{sy + t:.3f}" x2="{dim_x + t:.3f}" y2="{sy - t:.3f}" '
            f'stroke="{_DIM_COLOR}" stroke-width="{_DIM_STROKE_W}"/>'
        )
    mid_y = (sy1 + sy2) / 2.0
    char_w = _DIM_TEXT_SIZE * 0.55
    bg_w = max(8.0, len(label) * char_w + 2.0)
    bg_h = _DIM_TEXT_SIZE + 1.2
    lx = dim_x + 1.2
    els.append(
        f'<rect x="{lx - bg_h / 2:.3f}" y="{mid_y - bg_w / 2:.3f}" '
        f'width="{bg_h:.3f}" height="{bg_w:.3f}" fill="{_DIM_BG}" '
        f'transform="rotate(-90 {lx:.3f} {mid_y:.3f})"/>'
    )
    els.append(
        f'<text x="{lx:.3f}" y="{mid_y:.3f}" font-size="{_DIM_TEXT_SIZE}" '
        f'font-family="Helvetica, Arial, sans-serif" font-weight="400" '
        f'fill="{_DIM_COLOR}" text-anchor="middle" dominant-baseline="central" '
        f'transform="rotate(-90 {lx:.3f} {mid_y:.3f})">{escape(label)}</text>'
    )
    return els


def _overall_dims(
    bounds: Bounds2D,
    transform,
    x: float,
    y: float,
    width: float,
    height: float,
) -> List[str]:
    """Overall bounding-box dimension lines: width below frame, height to right."""
    world_w = bounds.max_x - bounds.min_x
    world_h = bounds.max_y - bounds.min_y
    if world_w < 0.01 or world_h < 0.01:
        return []

    sx_left, _ = transform(bounds.min_x, bounds.min_y)
    sx_right, _ = transform(bounds.max_x, bounds.min_y)
    _, sy_top = transform(bounds.min_x, bounds.max_y)
    _, sy_bot = transform(bounds.min_x, bounds.min_y)

    frame_bottom = y + height
    frame_right = x + width

    els: List[str] = []
    els.extend(_dim_h(sx_left, sx_right, frame_bottom + _DIM_GAP, f"{world_w:.2f} m", frame_bottom))
    els.extend(_dim_v(sy_top, sy_bot, frame_right + _DIM_GAP, f"{world_h:.2f} m", frame_right))
    return els


def _elevation_storey_lines(
    storeys: list,
    transform,
    bounds: Bounds2D,
    x: float,
    y: float,
    width: float,
    height: float,
) -> List[str]:
    """Dashed storey-level lines across the elevation with elevation labels."""
    els: List[str] = []
    frame_left = x
    frame_right = x + width
    for storey in storeys:
        elev = storey.elevation_m
        if elev is None:
            continue
        if elev < bounds.min_y - 0.1 or elev > bounds.max_y + 0.1:
            continue
        _, sy = transform(bounds.min_x, elev)
        if sy < y or sy > y + height:
            continue
        els.append(
            f'<line x1="{frame_left:.3f}" y1="{sy:.3f}" x2="{frame_right:.3f}" y2="{sy:.3f}" '
            f'stroke="{_DIM_COLOR}" stroke-width="0.15" stroke-dasharray="2 1.5"/>'
        )
        name_part = f"{storey.name} - " if storey.name else ""
        label = f"{name_part}+{elev:.2f} m"
        els.append(
            f'<text x="{frame_left + 1.2:.3f}" y="{sy - 0.8:.3f}" font-size="2.4" '
            f'font-family="Helvetica, Arial, sans-serif" font-weight="400" '
            f'fill="{_DIM_COLOR}">{escape(label)}</text>'
        )
    return els


def _elevation_schematic(storeys: list, x: float, y: float, width: float, height: float) -> str:
    """Schematic elevation used when OCCT geometry is unavailable.

    Draws storey level lines and height spans so the sheet is still informative
    rather than an empty box. A small note explains that full linework requires
    the [occt] extra.
    """
    elevations = sorted(
        (s.elevation_m for s in storeys if s.elevation_m is not None),
    )
    els: List[str] = [
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#fffefb" stroke="#cbd5e1" stroke-width="0.25"/>',
    ]

    if not elevations:
        els.append(_text(x + 4.0, y + 10.0, "No elevation geometry available for this view.", 4.0))
        els.append(_text(x + 4.0, y + 17.0, "Install the [occt] extra to populate elevations.", 3.5, fill="#475569"))
        return "\n".join(els)

    elev_min = elevations[0]
    # assume ~3 m top-storey headroom when computing total height
    top_headroom = 3.0
    elev_max = elevations[-1] + top_headroom
    total_h = max(elev_max - elev_min, 1.0)

    padding = 8.0
    usable_h = height - padding * 2.0
    scale = usable_h / total_h
    bar_x = x + 14.0

    def _ey(elev: float) -> float:
        return round(y + height - padding - (elev - elev_min) * scale, 3)

    ground_y = _ey(elev_min)
    top_y = _ey(elev_max)

    # Ground line
    els.append(
        f'<line x1="{x + 2:.1f}" y1="{ground_y}" x2="{x + width - 2:.1f}" y2="{ground_y}" '
        f'stroke="{_DIM_COLOR}" stroke-width="0.35"/>'
    )

    # Storey level lines and labels
    for storey in sorted(storeys, key=lambda s: s.elevation_m or 0.0):
        elev = storey.elevation_m
        if elev is None:
            continue
        sy = _ey(elev)
        if sy < y or sy > y + height:
            continue
        els.append(
            f'<line x1="{bar_x:.1f}" y1="{sy}" x2="{x + width - 6:.1f}" y2="{sy}" '
            f'stroke="{_DIM_COLOR}" stroke-width="0.18" stroke-dasharray="3 1.5"/>'
        )
        name_part = f"{storey.name}  " if storey.name else ""
        els.append(
            f'<text x="{bar_x:.1f}" y="{sy - 1.0}" font-size="3.0" '
            f'font-family="Helvetica, Arial, sans-serif" font-weight="400" '
            f'fill="{_DIM_COLOR}">{escape(f"{name_part}+{elev:.2f} m")}</text>'
        )
        # Short tick on the left margin
        els.append(
            f'<line x1="{x + 2:.1f}" y1="{sy}" x2="{bar_x - 1:.1f}" y2="{sy}" '
            f'stroke="{_DIM_COLOR}" stroke-width="0.25"/>'
        )

    # Total height dimension on the right edge
    dim_x = x + width - 4.0
    els.extend(_dim_v(top_y, ground_y, dim_x, f"{total_h:.2f} m", dim_x - 0.5))

    # Note
    els.append(
        _text(x + 4.0, y + height - 3.0,
              "Schematic — install [occt] extra for full linework", 2.8, fill="#64748b")
    )
    return "\n".join(els)


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
    preview_x = table_x + 35.5
    label_x = table_x + 61.0
    storey_x = table_x + 130.0
    count_x = table_x + 171.0
    table_width = 178.0
    table_height = row_height * (len(schedule.rows) + 1)

    rows = [
        _text(table_x, table_y - 5.0, "Deterministic IFC schedule extraction", 3.5, fill="#334155"),
        f'<rect x="{table_x}" y="{table_y}" width="{table_width}" height="{table_height}" fill="#fffefb" stroke="#0f172a" stroke-width="0.25"/>',
    ]

    for divider_x in (table_x + 34.0, table_x + 58.0, table_x + 126.0, table_x + 167.0):
        rows.append(
            f'<line x1="{divider_x}" y1="{table_y}" x2="{divider_x}" y2="{table_y + table_height}" stroke="#94a3b8" stroke-width="0.18"/>'
        )

    for row_index in range(1, len(schedule.rows) + 1):
        y = table_y + row_index * row_height
        rows.append(f'<line x1="{table_x}" y1="{y}" x2="{table_x + table_width}" y2="{y}" stroke="#cbd5e1" stroke-width="0.18"/>')

    rows.extend(
        [
            _text(class_x, table_y + 5.5, "Class", 3.8, weight="700"),
            _text(preview_x, table_y + 5.5, "Preview", 3.8, weight="700"),
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
                _schedule_preview_symbol(row.ifc_class, preview_x, table_y + index * row_height + 1.2, 20.0, 5.6),
                _text(label_x, baseline, _truncate(row.label, 31), 3.4),
                _text(storey_x, baseline, _truncate(row.storey_name, 15), 3.4),
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


def _schedule_preview_symbol(ifc_class: str, x: float, y: float, width: float, height: float) -> str:
    class_name = ifc_class.strip()
    stroke = "#1e3a5f"
    muted = "#64748b"
    fill = "#fffefb"
    cx = x + width / 2.0
    cy = y + height / 2.0
    left = x + 1.0
    right = x + width - 1.0
    top = y + 0.6
    bottom = y + height - 0.6

    if class_name == "IfcDoor":
        hinge_x = left + 2.0
        hinge_y = bottom
        leaf_x = hinge_x + min(7.0, width * 0.38)
        return "\n".join(
            [
                f'<line x1="{left:.3f}" y1="{bottom:.3f}" x2="{right:.3f}" y2="{bottom:.3f}" stroke="{muted}" stroke-width="0.18"/>',
                f'<line x1="{hinge_x:.3f}" y1="{hinge_y:.3f}" x2="{leaf_x:.3f}" y2="{top:.3f}" stroke="{stroke}" stroke-width="0.35"/>',
                f'<path d="M {hinge_x:.3f} {hinge_y:.3f} L {leaf_x:.3f} {hinge_y:.3f} L {leaf_x:.3f} {top:.3f}" fill="none" stroke="{stroke}" stroke-width="0.16"/>',
            ]
        )
    if class_name == "IfcWindow":
        return "\n".join(
            [
                f'<rect x="{left:.3f}" y="{cy - 1.3:.3f}" width="{right - left:.3f}" height="2.6" fill="{fill}" stroke="{stroke}" stroke-width="0.28"/>',
                f'<line x1="{cx:.3f}" y1="{cy - 1.3:.3f}" x2="{cx:.3f}" y2="{cy + 1.3:.3f}" stroke="{stroke}" stroke-width="0.18"/>',
                f'<line x1="{left + 2.0:.3f}" y1="{cy:.3f}" x2="{right - 2.0:.3f}" y2="{cy:.3f}" stroke="{muted}" stroke-width="0.14"/>',
            ]
        )
    if class_name == "IfcStair":
        step_w = (right - left) / 5.0
        segments = [f"M {left:.3f} {bottom:.3f}"]
        for step in range(1, 6):
            sx = left + step * step_w
            sy = bottom - step * ((bottom - top) / 5.0)
            segments.append(f"L {sx:.3f} {bottom - (step - 1) * ((bottom - top) / 5.0):.3f}")
            segments.append(f"L {sx:.3f} {sy:.3f}")
        return "\n".join(
            [
                f'<path d="{" ".join(segments)}" fill="none" stroke="{stroke}" stroke-width="0.24"/>',
                f'<path d="M {left + 2.0:.3f} {bottom - 0.4:.3f} L {right - 2.0:.3f} {top + 0.4:.3f}" fill="none" stroke="{muted}" stroke-width="0.16"/>',
            ]
        )
    if class_name == "IfcRamp":
        return f'<path d="M {left:.3f} {bottom:.3f} L {right:.3f} {bottom:.3f} L {right:.3f} {top:.3f} Z" fill="#e0f2fe" stroke="{stroke}" stroke-width="0.24"/>'
    if class_name == "IfcSpace":
        return "\n".join(
            [
                f'<rect x="{left:.3f}" y="{top:.3f}" width="{right - left:.3f}" height="{bottom - top:.3f}" fill="#ffffff" stroke="#b45309" stroke-width="0.2"/>',
                _text(cx - 1.0, cy + 1.0, "R", 2.8, fill="#92400e", weight="700"),
            ]
        )
    if class_name in {"IfcColumn", "IfcMember"}:
        size = min(width, height) - 1.2
        return f'<rect x="{cx - size / 2:.3f}" y="{cy - size / 2:.3f}" width="{size:.3f}" height="{size:.3f}" fill="#d6b39b" stroke="#111827" stroke-width="0.28"/>'
    if class_name == "IfcBeam":
        return f'<rect x="{left:.3f}" y="{cy - 1.1:.3f}" width="{right - left:.3f}" height="2.2" fill="#d6b39b" stroke="#111827" stroke-width="0.24"/>'
    if class_name == "IfcSlab":
        return "\n".join(
            [
                f'<rect x="{left:.3f}" y="{cy - 1.4:.3f}" width="{right - left:.3f}" height="2.8" fill="#e5e7eb" stroke="#334155" stroke-width="0.2"/>',
                f'<line x1="{left + 1.5:.3f}" y1="{cy + 1.4:.3f}" x2="{right - 1.5:.3f}" y2="{cy - 1.4:.3f}" stroke="{muted}" stroke-width="0.14"/>',
            ]
        )
    return f'<line x1="{left:.3f}" y1="{cy:.3f}" x2="{right:.3f}" y2="{cy:.3f}" stroke="{muted}" stroke-width="0.2"/>'


def render_view_svg(
    model: NormalizedModel,
    view: PlannedView,
    geometry: GeometrySummary,
    profile: StyleProfile,
) -> str:
    is_elevation = view.view_kind in ELEVATION_VIEW_KINDS
    if is_elevation:
        return _render_elevation_svg(model, view, geometry, profile)

    drawing = _plan_drawing(geometry, profile, x=20.0, y=38.0, width=170.0, height=150.0)
    feature_counts = _feature_annotation_counts(geometry)
    info_lines = [
        ("Storey", view.storey_name),
        ("Storey elev. (m)", _format_optional_float(view.storey_elevation_m)),
        ("Cut plane (m)", f"{view.cut_plane_m:.2f}"),
        ("Geometry backend", geometry.backend),
        ("Source elements", str(geometry.source_elements)),
        ("Line paths", str(geometry.path_count)),
        ("Stair arrows", str(feature_counts["IfcStair"])),
        ("Room tags", str(feature_counts["IfcSpace"])),
        ("Cut classes", _format_class_counts(geometry.cut_candidates)),
        ("Proj. classes", _format_class_counts(geometry.projection_candidates)),
    ]
    panel = _bottom_panel(info_lines, geometry.notes, profile)
    return _wrap_sheet(
        title=view.title,
        sheet_id=view.sheet_id,
        subtitle="Real IFC-driven floor-plan linework prototype",
        body="\n".join([drawing, panel]),
        profile=profile,
    )


def _render_elevation_svg(
    model: NormalizedModel,
    view: PlannedView,
    geometry: GeometrySummary,
    profile: StyleProfile,
) -> str:
    """Elevation sheet: projected linework with storey levels and dimension lines.

    Uses the same typed-linework renderer as plans when a ``ViewLinework`` is
    present. When geometry is empty (e.g. OCCT unavailable), renders an
    explanatory panel so the sheet stays deterministic.
    """
    x, y, width, height = 20.0, 38.0, 170.0, 150.0
    if geometry.bounds is not None and geometry.linework is not None and geometry.linework.lines:
        drawing = _plan_linework_typed(geometry, profile, x, y, width, height, with_features=False)
    elif geometry.bounds is not None and geometry.paths:
        drawing = _plan_linework(geometry, profile, x, y, width, height, with_features=False)
    else:
        drawing = _elevation_schematic(model.storeys, x, y, width, height)

    annotation_parts = [drawing]
    if geometry.bounds is not None:
        transform = _build_transform(geometry.bounds, x, y, width, height)
        annotation_parts.extend(_elevation_storey_lines(model.storeys, transform, geometry.bounds, x, y, width, height))
        annotation_parts.extend(_overall_dims(geometry.bounds, transform, x, y, width, height))

    info_lines = [
        ("View", view.title),
        ("View kind", view.view_kind),
        ("Geometry backend", geometry.backend),
        ("Source elements", str(geometry.source_elements)),
        ("Projected lines", str((geometry.linework_counts or {}).get("PROJECTED", 0))),
        ("Proj. classes", _format_class_counts(geometry.projection_candidates)),
    ]
    panel = _bottom_panel(info_lines, geometry.notes, profile)
    return _wrap_sheet(
        title=view.title,
        sheet_id=view.sheet_id,
        subtitle="Projected elevation linework (owned OCCT path)",
        body="\n".join(annotation_parts + [panel]),
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


# Bottom-panel layout constants. Two columns sit between the drawing region
# (ends at y=190) and the page title block (starts at y=265 in default A4):
#   - left column: info-lines (label / value pairs)
#   - right column: notes (truncated/wrapped to stay above the title block)
_BOTTOM_PANEL_TOP_Y = 198.0
_BOTTOM_PANEL_BOTTOM_Y = 262.0
_BOTTOM_PANEL_LEFT_X = 20.0
_BOTTOM_PANEL_VALUE_X = 58.0
_BOTTOM_PANEL_RIGHT_X = 110.0
_BOTTOM_PANEL_RIGHT_END_X = 198.0
_INFO_STEP_Y = 5.6
_NOTE_STEP_Y = 4.2
_NOTE_FONT_SIZE = 3.2
_NOTE_MAX_CHARS_PER_LINE = 72


def _bottom_panel(
    info_lines: Iterable[Tuple[str, str]],
    notes: Iterable[str],
    profile: StyleProfile,
) -> str:
    """Render the info + notes panel under a plan/elevation drawing.

    Both columns are clipped at ``_BOTTOM_PANEL_BOTTOM_Y`` so neither bleeds
    into the title block, regardless of input length. Overflowing notes get
    a single "+N more" tail entry so the reader knows information was elided.
    """
    info_lines = list(info_lines)
    notes = list(notes)
    rows: List[str] = [_text(_BOTTOM_PANEL_LEFT_X, _BOTTOM_PANEL_TOP_Y - 3.5, "Sheet info", 3.6, weight="700", fill="#334155")]
    y = _BOTTOM_PANEL_TOP_Y
    for label, value in info_lines:
        if y > _BOTTOM_PANEL_BOTTOM_Y:
            break
        rows.append(_text(_BOTTOM_PANEL_LEFT_X, y, label, 3.4, weight="700"))
        rows.append(_text(_BOTTOM_PANEL_VALUE_X, y, _truncate(value, 40), 3.4))
        y += _INFO_STEP_Y

    rows.append(_text(_BOTTOM_PANEL_RIGHT_X, _BOTTOM_PANEL_TOP_Y - 3.5, "Notes", 3.6, weight="700", fill="#334155"))
    note_y = _BOTTOM_PANEL_TOP_Y
    wrapped: List[str] = []
    for note in notes:
        wrapped.extend(_wrap_note(str(note), _NOTE_MAX_CHARS_PER_LINE))
    available = max(0, int((_BOTTOM_PANEL_BOTTOM_Y - note_y) / _NOTE_STEP_Y))
    if len(wrapped) > available and available > 0:
        kept = wrapped[: available - 1]
        omitted = len(wrapped) - len(kept)
        kept.append(f"+ {omitted} more")
        wrapped = kept
    for line in wrapped:
        if note_y > _BOTTOM_PANEL_BOTTOM_Y:
            break
        rows.append(_text(_BOTTOM_PANEL_RIGHT_X, note_y, line, _NOTE_FONT_SIZE))
        note_y += _NOTE_STEP_Y
    return "\n".join(rows)


def _wrap_note(text: str, max_chars: int) -> List[str]:
    text = text.strip()
    if not text:
        return []
    prefix = "- "
    body = text
    lines: List[str] = []
    while body:
        chunk = body[: max_chars - len(prefix)]
        if len(body) > len(chunk):
            split = chunk.rfind(" ")
            if split > max_chars // 2:
                chunk = chunk[:split]
        lines.append(prefix + chunk.rstrip())
        body = body[len(chunk):].lstrip()
        prefix = "  "
    return lines


def _plan_drawing(geometry: GeometrySummary, profile: StyleProfile, x: float, y: float, width: float, height: float) -> str:
    if geometry.bounds is not None and geometry.linework is not None and geometry.linework.lines:
        return _plan_linework_typed(geometry, profile, x, y, width, height)
    if geometry.bounds is not None and geometry.paths:
        return _plan_linework(geometry, profile, x, y, width, height)
    if geometry.bounds is not None and geometry.feature_anchors:
        bounds = geometry.bounds
        transform = _build_transform(bounds, x, y, width, height)
        drawing = [
            _text(x, y - 5.0, "Plan features from IFC semantic anchors", 3.5, fill="#334155"),
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#fffefb" stroke="#cbd5e1" stroke-width="0.25"/>',
        ]
        drawing.extend(_feature_annotations(geometry, profile, transform, x, y, width, height))
        drawing.extend(_overall_dims(bounds, transform, x, y, width, height))
        drawing.append(_text(x + 2.0, y + height - 3.0, _format_bounds(bounds), 2.7, fill="#475569"))
        return "\n".join(drawing)

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
    drawing.extend(_feature_annotations(geometry, profile, transform, x, y, width, height))
    drawing.extend(_overall_dims(bounds, transform, x, y, width, height))
    drawing.append(_text(x + 2.0, y + height - 3.0, _format_bounds(bounds), 2.7, fill="#475569"))
    return "\n".join(drawing)


def _plan_linework(geometry: GeometrySummary, profile: StyleProfile, x: float, y: float, width: float, height: float, with_features: bool = True) -> str:
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
    if with_features:
        drawing.extend(_feature_annotations(geometry, profile, transform, x, y, width, height))
    drawing.extend(_overall_dims(bounds, transform, x, y, width, height))
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


_TYPED_LINEWEIGHT_KEY = {
    LineweightClass.HEAVY: ("cut_primary", 0.35),
    LineweightClass.MEDIUM: ("cut_secondary", 0.25),
    LineweightClass.LIGHT: ("projected", 0.18),
    LineweightClass.FINE: ("overhead", 0.13),
}

_TYPED_KIND_STROKE = {
    LineKind.CUT: ("#111827", None),
    LineKind.PROJECTED: ("#475569", None),
    LineKind.HIDDEN: ("#475569", "1.3 1.3"),
    LineKind.OUTLINE: ("#334155", None),
}


def _lineweight_for_typed_line(line: TypedLine2D, profile: StyleProfile) -> float:
    key, default = _TYPED_LINEWEIGHT_KEY.get(line.lineweight_class, ("projected", 0.18))
    return profile.lineweights_mm.get(key, default)


def _plan_linework_typed(
    geometry: GeometrySummary,
    profile: StyleProfile,
    x: float,
    y: float,
    width: float,
    height: float,
    with_features: bool = True,
) -> str:
    bounds = geometry.bounds
    assert bounds is not None
    assert geometry.linework is not None
    transform = _build_transform(bounds, x, y, width, height)
    drawing = [
        _text(x, y - 5.0, "Plan linework from typed geometry kernel", 3.5, fill="#334155"),
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#fffefb" stroke="#cbd5e1" stroke-width="0.25"/>',
    ]
    # Deterministic z-order: PROJECTED -> HIDDEN -> OUTLINE -> CUT (cut on top)
    kind_order = {LineKind.PROJECTED: 0, LineKind.HIDDEN: 1, LineKind.OUTLINE: 2, LineKind.CUT: 3}
    sorted_lines = sorted(
        geometry.linework.lines,
        key=lambda line: (kind_order.get(line.kind, 9), line.z_order_hint, typed_line_sort_key(line)),
    )
    for line in sorted_lines:
        if not line.points:
            continue
        stroke, dash = _TYPED_KIND_STROKE.get(line.kind, ("#475569", None))
        drawing.append(
            _typed_line_path(
                line,
                transform,
                stroke=stroke,
                stroke_width=_lineweight_for_typed_line(line, profile),
                dash=dash,
            )
        )
    if with_features:
        drawing.extend(_feature_annotations(geometry, profile, transform, x, y, width, height))
    drawing.extend(_overall_dims(bounds, transform, x, y, width, height))
    drawing.append(_text(x + 2.0, y + height - 3.0, _format_bounds(bounds), 2.7, fill="#475569"))
    return "\n".join(drawing)


def _typed_line_path(
    line: TypedLine2D,
    transform,
    stroke: str,
    stroke_width: float,
    dash: str | None = None,
) -> str:
    commands: List[str] = []
    start_x, start_y = transform(line.points[0].x, line.points[0].y)
    commands.append(f"M {start_x} {start_y}")
    for point in line.points[1:]:
        x, y = transform(point.x, point.y)
        commands.append(f"L {x} {y}")
    if line.closed:
        commands.append("Z")
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<path d="{" ".join(commands)}" fill="none" '
        f'stroke="{stroke}" stroke-width="{stroke_width}" '
        f'stroke-linejoin="round" stroke-linecap="round"{dash_attr}/>'
    )


def _lineweight_for_path(path: VectorPath, profile: StyleProfile, role: str) -> float:
    if role == "projection":
        return profile.lineweights_mm.get("projected", 0.18)
    if path.ifc_class in PRIMARY_CUT_CLASSES:
        return profile.lineweights_mm.get("cut_primary", 0.35)
    return profile.lineweights_mm.get("cut_secondary", 0.25)


def _feature_annotations(
    geometry: GeometrySummary,
    profile: StyleProfile,
    transform,
    x: float,
    y: float,
    width: float,
    height: float,
) -> List[str]:
    overlay = profile.floor_plan.feature_overlay
    if not overlay.enabled:
        return []
    primitives = _collect_feature_primitives(geometry, overlay)
    drawing: List[str] = []

    max_stair_arrows = max(0, int(overlay.max_stair_arrows))
    max_room_tags = max(0, int(overlay.max_room_tags))
    max_door_symbols = max(0, int(overlay.max_door_symbols))
    stair_arrows = primitives["IfcStair"][:max_stair_arrows] if overlay.stairs_enabled else []
    room_tags = primitives["IfcSpace"][:max_room_tags] if overlay.rooms_enabled else []
    door_symbols = primitives["IfcDoor"][:max_door_symbols] if overlay.doors_enabled else []

    placed_boxes: List[Tuple[float, float, float, float]] = []
    offsets = _placement_offsets(step=3.2, rings=6)
    frame = (x, y, x + width, y + height)

    # Doors draw before stair/room labels so leaders / labels paint on top.
    if door_symbols:
        page_scale = _page_units_per_world_meter(transform)
        for primitive in door_symbols:
            anchor_sx, anchor_sy = transform(primitive.anchor.x, primitive.anchor.y)
            ux, uy = _feature_direction_screen(transform, primitive)
            door_width_m = primitive.width_m or overlay.door_default_width_m
            drawing.extend(
                _door_swing_symbol(
                    anchor_sx,
                    anchor_sy,
                    ux,
                    uy,
                    door_width_page=max(1.0, door_width_m * page_scale),
                    handedness=primitive.handedness,
                    frame_color=overlay.door_color,
                    arc_color=overlay.door_arc_color,
                )
            )

    for primitive in stair_arrows:
        anchor_sx, anchor_sy = transform(primitive.anchor.x, primitive.anchor.y)
        ux, uy = _feature_direction_screen(transform, primitive)
        sx, sy, bbox, moved = _resolve_symbol_placement(
            symbol_kind="stair",
            anchor_sx=anchor_sx,
            anchor_sy=anchor_sy,
            ux=ux,
            uy=uy,
            offsets=offsets,
            placed_boxes=placed_boxes,
            frame=frame,
        )
        if moved and overlay.leader_enabled:
            drawing.append(
                f'<line x1="{round(anchor_sx, 3)}" y1="{round(anchor_sy, 3)}" '
                f'x2="{round(sx, 3)}" y2="{round(sy, 3)}" '
                f'stroke="{overlay.leader_color}" stroke-width="{overlay.leader_stroke_width}" '
                f'stroke-dasharray="{overlay.leader_dasharray}" data-feature="leader"/>'
            )
        drawing.extend(
            _stair_symbol(
                sx,
                sy,
                ux,
                uy,
                color=overlay.stair_color,
                label_text=overlay.stair_label.strip() or "UP",
            )
        )
        placed_boxes.append(bbox)

    for primitive in room_tags:
        anchor_sx, anchor_sy = transform(primitive.anchor.x, primitive.anchor.y)
        label = primitive.label or "ROOM"
        sx, sy, bbox, moved = _resolve_symbol_placement(
            symbol_kind="room",
            anchor_sx=anchor_sx,
            anchor_sy=anchor_sy,
            ux=1.0,
            uy=0.0,
            offsets=offsets,
            placed_boxes=placed_boxes,
            frame=frame,
            label=label,
        )
        if moved and overlay.leader_enabled:
            drawing.append(
                f'<line x1="{round(anchor_sx, 3)}" y1="{round(anchor_sy, 3)}" '
                f'x2="{round(sx, 3)}" y2="{round(sy, 3)}" '
                f'stroke="{overlay.leader_color}" stroke-width="{overlay.leader_stroke_width}" '
                f'stroke-dasharray="{overlay.leader_dasharray}" data-feature="leader"/>'
            )
        drawing.extend(
            _room_tag_symbol(
                sx,
                sy,
                label,
                fill_color=overlay.room_fill_color,
                stroke_color=overlay.room_stroke_color,
                text_color=overlay.room_text_color,
            )
        )
        placed_boxes.append(bbox)

    stair_total = len(primitives["IfcStair"])
    room_total = len(primitives["IfcSpace"])
    door_total = len(primitives["IfcDoor"])
    suffix = ""
    if (
        (overlay.stairs_enabled and stair_total > max_stair_arrows)
        or (overlay.rooms_enabled and room_total > max_room_tags)
        or (overlay.doors_enabled and door_total > max_door_symbols)
    ):
        suffix = " (sampled)"
    if overlay.show_legend:
        # The "Doors" slot tracks our custom overlay only. When that overlay is
        # off we omit the slot entirely, because the serializer draws door
        # arcs as part of the linework regardless — printing "Doors: off"
        # then misleads the reader into thinking there are no doors on the
        # plan.
        parts = [
            f"Stairs: {_feature_count_token(overlay.stairs_enabled, stair_total)}",
            f"Rooms: {_feature_count_token(overlay.rooms_enabled, room_total)}",
        ]
        if overlay.doors_enabled:
            parts.append(f"Doors: {_feature_count_token(True, door_total)}")
        legend = "Feature overlay | " + " | ".join(parts) + suffix
        drawing.append(_text(x + 2.0, y + 4.5, legend, 2.8, fill=overlay.legend_color))
    return drawing


def _page_units_per_world_meter(transform) -> float:
    """How many page units one world-meter spans after applying the view transform."""
    x0, _ = transform(0.0, 0.0)
    x1, _ = transform(1.0, 0.0)
    return max(0.5, abs(x1 - x0))


def _door_swing_symbol(
    sx: float,
    sy: float,
    ux: float,
    uy: float,
    door_width_page: float,
    handedness: str | None,
    frame_color: str,
    arc_color: str,
) -> List[str]:
    """Draw a planar door symbol at (sx, sy) opening in direction (ux, uy).

    Symbol geometry (architectural convention):
      - hinge at the anchor point
      - frame: short line along the wall (perpendicular to opening)
      - leaf: line from hinge in the opening direction, length == door width
      - arc: quarter-circle from leaf tip back to the opposite jamb

    Handedness flips the perpendicular side: "left" hinges on the left of the
    opening direction (anchor sits on the right jamb); "right" mirrors it.
    Falls back to a deterministic side when handedness is missing.
    """
    norm = math.hypot(ux, uy)
    if norm < 1.0e-6:
        ux, uy = 1.0, 0.0
    else:
        ux, uy = ux / norm, uy / norm
    side = -1.0 if (handedness or "").strip().lower() == "right" else 1.0
    # SVG y-down: rotate +90deg in screen space yields (-uy, ux) which lies
    # to the left of the opening direction when looking at the page.
    px = -uy * side
    py = ux * side
    hinge_x, hinge_y = sx, sy
    jamb_x = sx + px * door_width_page
    jamb_y = sy + py * door_width_page
    leaf_tip_x = sx + ux * door_width_page
    leaf_tip_y = sy + uy * door_width_page
    # Approximate the swing as a polyline. The SVG ``A`` command is not in the
    # subset of the SVG-to-PDF parser we ship, so a piecewise straight path
    # keeps the output identical between SVG and PDF.
    segments = 12
    arc_d = [f"M {leaf_tip_x:.3f} {leaf_tip_y:.3f}"]
    # Quarter-circle from leaf_tip back to jamb, sweeping through (ux, uy) and
    # (px, py): each interpolated point sits on a circle of radius door_width_page
    # centred at the hinge, parameterised by angle theta in [0, pi/2].
    for step in range(1, segments + 1):
        theta = (math.pi / 2.0) * (step / segments)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        arc_x = hinge_x + (ux * cos_t + px * sin_t) * door_width_page
        arc_y = hinge_y + (uy * cos_t + py * sin_t) * door_width_page
        arc_d.append(f"L {arc_x:.3f} {arc_y:.3f}")
    return [
        # wall plane (frame) — short line along the opening
        f'<line x1="{hinge_x:.3f}" y1="{hinge_y:.3f}" x2="{jamb_x:.3f}" y2="{jamb_y:.3f}" '
        f'stroke="{frame_color}" stroke-width="0.18" data-feature="door-frame"/>',
        # door leaf
        f'<line x1="{hinge_x:.3f}" y1="{hinge_y:.3f}" x2="{leaf_tip_x:.3f}" y2="{leaf_tip_y:.3f}" '
        f'stroke="{frame_color}" stroke-width="0.28" data-feature="door-leaf"/>',
        # swing arc (quarter circle approximated by 12 line segments)
        f'<path d="{" ".join(arc_d)}" fill="none" '
        f'stroke="{arc_color}" stroke-width="0.14" stroke-dasharray="0.6 0.4" data-feature="door-arc"/>',
    ]


def _feature_count_token(enabled: bool, count: int) -> str:
    return str(count) if enabled else "off"


def _feature_annotation_counts(geometry: GeometrySummary) -> Dict[str, int]:
    primitives = _collect_feature_primitives(geometry)
    return {
        "IfcStair": len(primitives["IfcStair"]),
        "IfcSpace": len(primitives["IfcSpace"]),
    }


def _viewport_scale(bounds: Bounds2D, width: float, height: float, padding: float = 4.0) -> float:
    """Return the drawing scale in mm/m (sheet-space mm per world-space metre)."""
    world_w = max(bounds.max_x - bounds.min_x, 1.0e-6)
    world_h = max(bounds.max_y - bounds.min_y, 1.0e-6)
    return min((width - padding * 2.0) / world_w, (height - padding * 2.0) / world_h)


class _FeaturePrimitive:
    __slots__ = (
        "anchor",
        "dir_x",
        "dir_y",
        "length",
        "ifc_class",
        "label",
        "display_label",
        "width_m",
        "handedness",
    )

    def __init__(
        self,
        anchor: Point2D,
        dir_x: float,
        dir_y: float,
        length: float,
        ifc_class: str,
        label: str | None = None,
        display_label: str | None = None,
        width_m: float | None = None,
        handedness: str | None = None,
    ):
        self.anchor = anchor
        self.dir_x = dir_x
        self.dir_y = dir_y
        self.length = length
        self.ifc_class = ifc_class
        self.label = label
        self.display_label = display_label
        self.width_m = width_m
        self.handedness = handedness


def _collect_feature_primitives(
    geometry: GeometrySummary,
    overlay: FeatureOverlayRule | None = None,
) -> Dict[str, List[_FeaturePrimitive]]:
    overlay = overlay or FeatureOverlayRule()
    classes = ("IfcStair", "IfcSpace", "IfcDoor")
    grouped: Dict[str, Dict[Tuple[int, int], _FeaturePrimitive]] = {class_name: {} for class_name in classes}
    semantic_priority_length = 1000.0
    semantic_classes: set[str] = set()

    # Prefer IFC-semantic anchors when available (real element placements).
    for anchor in geometry.feature_anchors:
        class_name = anchor.ifc_class
        if class_name not in grouped:
            continue
        semantic_classes.add(class_name)
        bucket = _feature_bucket(anchor.anchor.x, anchor.anchor.y)
        primitive = _FeaturePrimitive(
            anchor=Point2D(x=round(anchor.anchor.x, 4), y=round(anchor.anchor.y, 4)),
            dir_x=anchor.dir_x,
            dir_y=anchor.dir_y,
            length=semantic_priority_length,
            ifc_class=class_name,
            label=anchor.label,
            display_label=anchor.display_label,
            width_m=anchor.width_m,
            handedness=anchor.door_handedness,
        )
        existing = grouped[class_name].get(bucket)
        if existing is None or primitive.length > existing.length:
            grouped[class_name][bucket] = primitive

    # Fallback/augmentation from geometry-derived class paths when anchors are missing.
    for class_name, points in _iter_class_points(geometry):
        if class_name not in grouped or len(points) < 2:
            continue
        if class_name in semantic_classes:
            continue
        dir_x, dir_y, length = _infer_direction(points)
        if length <= 1.0e-9:
            continue
        min_x = min(point.x for point in points)
        max_x = max(point.x for point in points)
        min_y = min(point.y for point in points)
        max_y = max(point.y for point in points)
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        bucket = _feature_bucket(center_x, center_y)
        primitive = _FeaturePrimitive(
            anchor=Point2D(x=round(center_x, 4), y=round(center_y, 4)),
            dir_x=dir_x,
            dir_y=dir_y,
            length=length,
            ifc_class=class_name,
        )
        existing = grouped[class_name].get(bucket)
        if existing is None or (existing.length < semantic_priority_length and primitive.length > existing.length):
            grouped[class_name][bucket] = primitive
    result: Dict[str, List[_FeaturePrimitive]] = {}
    for class_name in classes:
        result[class_name] = sorted(
            grouped[class_name].values(),
            key=lambda primitive: (primitive.anchor.y, primitive.anchor.x, -primitive.length),
        )
    result["IfcSpace"] = _label_rooms(result["IfcSpace"], overlay)
    return result


def _feature_bucket(x: float, y: float) -> Tuple[int, int]:
    # 0.6m bucket keeps deterministic dedupe and avoids marker storms on dense geometry.
    return (int(round(x / 0.6)), int(round(y / 0.6)))


def _feature_direction_screen(transform, primitive: _FeaturePrimitive) -> Tuple[float, float]:
    sx, sy = transform(primitive.anchor.x, primitive.anchor.y)
    tx, ty = transform(primitive.anchor.x + primitive.dir_x, primitive.anchor.y + primitive.dir_y)
    dx = tx - sx
    dy = ty - sy
    length = math.hypot(dx, dy)
    if length <= 1.0e-9:
        return 1.0, 0.0
    return dx / length, dy / length


def _infer_direction(points: List[Point2D]) -> Tuple[float, float, float]:
    if len(points) < 2:
        return 1.0, 0.0, 0.0
    start = points[0]
    end = points[-1]
    fallback_dx = end.x - start.x
    fallback_dy = end.y - start.y
    fallback_length = math.hypot(fallback_dx, fallback_dy)
    if fallback_length <= 1.0e-12:
        for idx in range(len(points) - 1):
            segment_dx = points[idx + 1].x - points[idx].x
            segment_dy = points[idx + 1].y - points[idx].y
            segment_length = math.hypot(segment_dx, segment_dy)
            if segment_length > 1.0e-12:
                fallback_dx = segment_dx
                fallback_dy = segment_dy
                fallback_length = segment_length
                break
    if fallback_length <= 1.0e-12:
        return 1.0, 0.0, 0.0

    mean_x = sum(point.x for point in points) / len(points)
    mean_y = sum(point.y for point in points) / len(points)
    var_xx = 0.0
    var_yy = 0.0
    cov_xy = 0.0
    for point in points:
        dx = point.x - mean_x
        dy = point.y - mean_y
        var_xx += dx * dx
        var_yy += dy * dy
        cov_xy += dx * dy
    if abs(var_xx - var_yy) + abs(cov_xy) <= 1.0e-12:
        return fallback_dx / fallback_length, fallback_dy / fallback_length, fallback_length

    theta = 0.5 * math.atan2(2.0 * cov_xy, var_xx - var_yy)
    ux = math.cos(theta)
    uy = math.sin(theta)
    if fallback_dx * ux + fallback_dy * uy < 0.0:
        ux = -ux
        uy = -uy
    return ux, uy, fallback_length


def _label_rooms(spaces: List[_FeaturePrimitive], overlay: FeatureOverlayRule) -> List[_FeaturePrimitive]:
    labeled: List[_FeaturePrimitive] = []
    mode = overlay.room_label_mode.strip().lower()
    prefix = overlay.room_label_prefix.strip()
    start_number = max(1, int(overlay.room_label_start))
    fixed_label = overlay.room_fixed_label.strip() or "ROOM"
    for index, primitive in enumerate(spaces, start=1):
        number = start_number + index - 1
        if mode == "fixed":
            label = fixed_label
        elif mode == "ifc_name":
            label = (primitive.display_label or primitive.label or "").strip() or f"{(prefix or 'R')}-{number:03d}"
        elif mode == "numeric":
            label = f"{number:03d}" if not prefix else f"{prefix}-{number:03d}"
        else:
            # Default policy keeps deterministic sequence and office prefix.
            label_prefix = prefix or "R"
            label = f"{label_prefix}-{number:03d}"
        labeled.append(
            _FeaturePrimitive(
                anchor=primitive.anchor,
                dir_x=primitive.dir_x,
                dir_y=primitive.dir_y,
                length=primitive.length,
                ifc_class=primitive.ifc_class,
                label=label,
                display_label=primitive.display_label,
            )
        )
    return labeled


def _placement_offsets(step: float, rings: int) -> List[Tuple[float, float]]:
    offsets: List[Tuple[float, float]] = [(0.0, 0.0)]
    for ring in range(1, rings + 1):
        distance = step * ring
        offsets.extend(
            [
                (distance, 0.0),
                (-distance, 0.0),
                (0.0, distance),
                (0.0, -distance),
                (distance, distance),
                (-distance, distance),
                (distance, -distance),
                (-distance, -distance),
            ]
        )
    return offsets


def _resolve_symbol_placement(
    symbol_kind: str,
    anchor_sx: float,
    anchor_sy: float,
    ux: float,
    uy: float,
    offsets: List[Tuple[float, float]],
    placed_boxes: List[Tuple[float, float, float, float]],
    frame: Tuple[float, float, float, float],
    label: str | None = None,
) -> Tuple[float, float, Tuple[float, float, float, float], bool]:
    for dx, dy in offsets:
        sx = anchor_sx + dx
        sy = anchor_sy + dy
        bbox = _symbol_bbox(symbol_kind, sx, sy, ux, uy, label=label)
        if not _bbox_inside(bbox, frame):
            continue
        if any(_bbox_intersects(bbox, existing, padding=0.6) for existing in placed_boxes):
            continue
        moved = abs(dx) > 1.0e-9 or abs(dy) > 1.0e-9
        return sx, sy, bbox, moved
    fallback_bbox = _symbol_bbox(symbol_kind, anchor_sx, anchor_sy, ux, uy, label=label)
    return anchor_sx, anchor_sy, fallback_bbox, False


def _symbol_bbox(
    symbol_kind: str,
    sx: float,
    sy: float,
    ux: float,
    uy: float,
    label: str | None = None,
) -> Tuple[float, float, float, float]:
    if symbol_kind == "stair":
        points = _stair_anchor_points(sx, sy, ux, uy)
        margin = 1.4
    else:
        points = _room_tag_anchor_points(sx, sy, label or "ROOM")
        margin = 1.0
    min_x = min(point[0] for point in points) - margin
    min_y = min(point[1] for point in points) - margin
    max_x = max(point[0] for point in points) + margin
    max_y = max(point[1] for point in points) + margin
    return (min_x, min_y, max_x, max_y)


def _bbox_inside(bbox: Tuple[float, float, float, float], frame: Tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = bbox
    fx0, fy0, fx1, fy1 = frame
    return x0 >= fx0 + 0.5 and y0 >= fy0 + 0.5 and x1 <= fx1 - 0.5 and y1 <= fy1 - 0.5


def _bbox_intersects(
    left: Tuple[float, float, float, float],
    right: Tuple[float, float, float, float],
    padding: float,
) -> bool:
    lx0, ly0, lx1, ly1 = left
    rx0, ry0, rx1, ry1 = right
    return not (
        lx1 + padding < rx0
        or rx1 + padding < lx0
        or ly1 + padding < ry0
        or ry1 + padding < ly0
    )


def _stair_symbol(
    sx: float,
    sy: float,
    ux: float,
    uy: float,
    color: str,
    label_text: str,
) -> List[str]:
    drawing: List[str] = []
    half = 3.2
    start_x = sx - ux * half
    start_y = sy - uy * half
    end_x = sx + ux * half
    end_y = sy + uy * half
    perp_x = -uy
    perp_y = ux
    tip_back = 1.8
    wing = 0.95
    left_x = end_x - ux * tip_back + perp_x * wing
    left_y = end_y - uy * tip_back + perp_y * wing
    right_x = end_x - ux * tip_back - perp_x * wing
    right_y = end_y - uy * tip_back - perp_y * wing

    drawing.append(
        f'<line x1="{round(start_x, 3)}" y1="{round(start_y, 3)}" x2="{round(end_x, 3)}" y2="{round(end_y, 3)}" '
        f'stroke="{color}" stroke-width="0.28"/>'
    )
    drawing.append(
        f'<path d="M {round(left_x, 3)} {round(left_y, 3)} L {round(end_x, 3)} {round(end_y, 3)} '
        f'L {round(right_x, 3)} {round(right_y, 3)} Z" fill="{color}" stroke="none"/>'
    )
    label_x = end_x + perp_x * 1.4
    label_y = end_y + perp_y * 1.4
    drawing.append(_text(label_x, label_y, label_text, 2.3, weight="700", fill=color))
    return drawing


def _room_tag_symbol(
    sx: float,
    sy: float,
    label: str,
    fill_color: str,
    stroke_color: str,
    text_color: str,
) -> List[str]:
    half_w = max(4.5, 1.4 + len(label) * 0.8)
    half_h = 2.4
    x = sx - half_w
    y = sy - half_h
    return [
        f'<rect x="{round(x, 3)}" y="{round(y, 3)}" width="{round(half_w * 2.0, 3)}" '
        f'height="{round(half_h * 2.0, 3)}" fill="{fill_color}" stroke="{stroke_color}" stroke-width="0.22" rx="0.7" ry="0.7"/>',
        _text(sx - (len(label) * 0.82) / 2.0, sy + 0.8, label, 2.2, weight="700", fill=text_color),
    ]


def _stair_anchor_points(sx: float, sy: float, ux: float, uy: float) -> List[Tuple[float, float]]:
    half = 3.2
    start_x = sx - ux * half
    start_y = sy - uy * half
    end_x = sx + ux * half
    end_y = sy + uy * half
    perp_x = -uy
    perp_y = ux
    tip_back = 1.8
    wing = 0.95
    left_x = end_x - ux * tip_back + perp_x * wing
    left_y = end_y - uy * tip_back + perp_y * wing
    right_x = end_x - ux * tip_back - perp_x * wing
    right_y = end_y - uy * tip_back - perp_y * wing
    label_x = end_x + perp_x * 1.4
    label_y = end_y + perp_y * 1.4
    return [
        (start_x, start_y),
        (end_x, end_y),
        (left_x, left_y),
        (right_x, right_y),
        (label_x, label_y),
    ]


def _room_tag_anchor_points(sx: float, sy: float, label: str) -> List[Tuple[float, float]]:
    half_w = max(4.5, 1.4 + len(label) * 0.8)
    half_h = 2.4
    return [
        (sx - half_w, sy - half_h),
        (sx + half_w, sy - half_h),
        (sx + half_w, sy + half_h),
        (sx - half_w, sy + half_h),
    ]


def _iter_class_points(geometry: GeometrySummary):
    if geometry.linework is not None:
        for line in geometry.linework.lines:
            if line.source_ifc_class and line.points:
                yield line.source_ifc_class, line.points
    for path in geometry.paths:
        if path.ifc_class and path.points:
            yield path.ifc_class, path.points


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
