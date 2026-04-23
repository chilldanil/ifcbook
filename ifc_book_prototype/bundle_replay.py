from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import List

from .domain import FeatureOverlayRule, PipelineManifest, SheetArtifact, StyleProfile, to_primitive
from .geometry_metrics import summarize_geometry_runtime
from .render_pdf import write_pdf_from_svg_sheets


METADATA_FILENAMES = (
    "preflight.json",
    "normalized_model.json",
    "view_manifest.json",
    "view_geometry.json",
    "geometry_runtime_summary.json",
    "schedule_manifest.json",
)

CAPABILITY_CLASSES = (
    "IFCSPACE",
    "IFCDOOR",
    "IFCWINDOW",
    "IFCSTAIR",
    "IFCRAMP",
    "IFCWALL",
    "IFCSLAB",
    "IFCCOLUMN",
    "IFCBEAM",
    "IFCMEMBER",
)


def replay_bundle(bundle_dir: Path, output_dir: Path, profile: StyleProfile | None = None) -> PipelineManifest:
    bundle_dir = bundle_dir.resolve()
    output_dir = output_dir.resolve()
    metadata_dir = output_dir / "metadata"
    sheets_dir = output_dir / "sheets"
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(exist_ok=True)
    sheets_dir.mkdir(exist_ok=True)

    source_manifest = _load_json(bundle_dir / "manifest.json")
    warnings = list(source_manifest.get("warnings", []))
    source_preflight = _load_optional_json(bundle_dir / "metadata" / "preflight.json") or {}
    source_counts = source_preflight.get("entity_counts", {}) if isinstance(source_preflight, dict) else {}
    replay_door_count = int(source_counts.get("IFCDOOR", 0) or 0)
    replay_stair_count = int(source_counts.get("IFCSTAIR", 0) or 0)
    replay_room_count = int(source_counts.get("IFCSPACE", 0) or 0)
    overlay_style = profile.floor_plan.feature_overlay if profile is not None else FeatureOverlayRule()
    overlay_by_sheet = _build_view_overlay_by_sheet(bundle_dir)

    copied_sheets: List[SheetArtifact] = []
    for sheet in source_manifest.get("sheets", []):
        source_svg = _resolve_source_path(bundle_dir, sheet.get("svg_path", ""), bundle_dir / "sheets")
        if source_svg is None:
            warnings.append(f"Missing source sheet SVG for {sheet.get('sheet_id', 'unknown')}.")
            continue
        destination_svg = sheets_dir / source_svg.name
        shutil.copy2(source_svg, destination_svg)
        if sheet.get("role") == "view":
            _inject_replay_feature_overlay(
                destination_svg,
                door_count=replay_door_count,
                stair_count=replay_stair_count,
                room_count=replay_room_count,
                overlay_style=overlay_style,
                view_overlay=overlay_by_sheet.get(sheet.get("sheet_id", "")),
            )
        copied_sheets.append(
            SheetArtifact(
                sheet_id=sheet["sheet_id"],
                title=sheet["title"],
                svg_path=str(destination_svg),
                page_number=int(sheet["page_number"]),
                role=sheet["role"],
            )
        )

    destination_pdf = output_dir / "book.pdf"
    try:
        ordered_sheets = [
            Path(sheet.svg_path)
            for sheet in sorted(copied_sheets, key=lambda sheet: sheet.page_number)
        ]
        write_pdf_from_svg_sheets(destination_pdf, ordered_sheets)
        copied_pdf_path = str(destination_pdf)
    except Exception as exc:
        copied_pdf_path = ""
        warnings.append(f"Bundle replay PDF assembly failed: {exc!s}")
        source_pdf = _resolve_source_path(bundle_dir, source_manifest.get("pdf_path", ""), bundle_dir)
        if source_pdf is not None:
            shutil.copy2(source_pdf, destination_pdf)
            copied_pdf_path = str(destination_pdf)
            warnings.append("Fell back to copying the source bundle PDF.")
        else:
            warnings.append("Bundle replay did not find a source PDF to copy.")

    for filename in METADATA_FILENAMES:
        source_file = bundle_dir / "metadata" / filename
        if source_file.exists():
            shutil.copy2(source_file, metadata_dir / filename)

    bundle_summary = _build_bundle_summary(bundle_dir, source_manifest, copied_sheets)
    runtime_summary = bundle_summary.get("geometry_runtime_summary")
    if runtime_summary is not None:
        (metadata_dir / "geometry_runtime_summary.json").write_text(
            json.dumps(runtime_summary, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
    (metadata_dir / "bundle_summary.json").write_text(
        json.dumps(bundle_summary, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    manifest = PipelineManifest(
        job_id=source_manifest["job_id"],
        input_sha256=source_manifest["input_sha256"],
        style_profile_id=source_manifest["style_profile_id"],
        model_hash=source_manifest["model_hash"],
        output_dir=str(output_dir),
        pdf_path=copied_pdf_path,
        sheets=copied_sheets,
        warnings=warnings,
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(to_primitive(manifest), indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _resolve_source_path(bundle_dir: Path, manifest_path: str, fallback_dir: Path) -> Path | None:
    candidates = []
    if manifest_path:
        candidates.append(Path(manifest_path))
        candidates.append(bundle_dir / Path(manifest_path).name)
        candidates.append(fallback_dir / Path(manifest_path).name)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _build_bundle_summary(bundle_dir: Path, source_manifest: dict, copied_sheets: List[SheetArtifact]) -> dict:
    preflight = _load_optional_json(bundle_dir / "metadata" / "preflight.json")
    normalized = _load_optional_json(bundle_dir / "metadata" / "normalized_model.json")
    view_manifest = _load_optional_json(bundle_dir / "metadata" / "view_manifest.json") or []
    schedule_manifest = _load_optional_json(bundle_dir / "metadata" / "schedule_manifest.json") or []
    geometry_runtime_summary = _load_optional_json(bundle_dir / "metadata" / "geometry_runtime_summary.json")
    if geometry_runtime_summary is None:
        view_geometry = _load_optional_json(bundle_dir / "metadata" / "view_geometry.json") or []
        geometry_runtime_summary = summarize_geometry_runtime(view_geometry)

    entity_counts = (preflight or {}).get("entity_counts", {})
    capability_counts = {name: int(entity_counts.get(name, 0)) for name in CAPABILITY_CLASSES}

    return {
        "source_bundle_dir": str(bundle_dir),
        "source_ifc_path": (preflight or {}).get("input_path", ""),
        "job_id": source_manifest.get("job_id", ""),
        "style_profile_id": source_manifest.get("style_profile_id", ""),
        "sheet_count": len(copied_sheets),
        "view_count": len([sheet for sheet in copied_sheets if sheet.role == "view"]),
        "schedule_count": len([sheet for sheet in copied_sheets if sheet.role == "schedule"]),
        "schedule_categories": sorted({sheet.get("category", "") for sheet in schedule_manifest if sheet.get("category")}),
        "storey_count": len((normalized or {}).get("storeys", [])),
        "view_titles": [view.get("title", "") for view in view_manifest],
        "geometry_runtime_summary": geometry_runtime_summary,
        "capability_counts": capability_counts,
        "capabilities": {
            "has_spaces": capability_counts["IFCSPACE"] > 0,
            "has_openings": capability_counts["IFCDOOR"] > 0 or capability_counts["IFCWINDOW"] > 0,
            "has_circulation": capability_counts["IFCSTAIR"] > 0 or capability_counts["IFCRAMP"] > 0,
            "has_structural_types": any(capability_counts[name] > 0 for name in ("IFCCOLUMN", "IFCBEAM", "IFCMEMBER", "IFCSLAB")),
        },
    }


def _load_optional_json(path: Path):
    if not path.exists():
        return None
    return _load_json(path)


def _inject_replay_feature_overlay(
    svg_path: Path,
    door_count: int,
    stair_count: int,
    room_count: int = 0,
    overlay_style: FeatureOverlayRule | None = None,
    view_overlay: dict | None = None,
) -> None:
    overlay_style = overlay_style or FeatureOverlayRule()
    if not overlay_style.enabled:
        return
    if door_count <= 0 and stair_count <= 0 and room_count <= 0:
        return
    text = svg_path.read_text(encoding="utf-8")
    marker = "</svg>"
    if marker not in text:
        return
    has_existing_view_overlay = "Feature overlay |" in text
    door_enabled = bool(overlay_style.doors_enabled)
    stair_enabled = bool(overlay_style.stairs_enabled)
    room_enabled = bool(overlay_style.rooms_enabled)
    door_label = overlay_style.door_label.strip() or "D"
    stair_label = overlay_style.stair_label.strip() or "UP"
    room_preview = _room_preview_label(overlay_style)
    overlay_parts = [
        f'  <text x="22.0" y="33.0" font-size="2.8" font-family="Helvetica, Arial, sans-serif" font-weight="400" fill="{overlay_style.legend_color}">'
        f"Replay feature overlay | Doors: {_feature_count_token(door_enabled, door_count)} | Stairs: {_feature_count_token(stair_enabled, stair_count)} | Rooms: {_feature_count_token(room_enabled, room_count)}"
        "</text>",
    ]
    if door_enabled and door_count > 0:
        overlay_parts.extend(
            [
                f'  <circle cx="22.0" cy="36.4" r="1.4" fill="#ffffff" stroke="{overlay_style.door_color}" stroke-width="0.22"/>',
                f'  <text x="21.2" y="37.35" font-size="2.3" font-family="Helvetica, Arial, sans-serif" font-weight="700" fill="{overlay_style.door_color}">{door_label}</text>',
                f'  <text x="25.0" y="37.35" font-size="2.6" font-family="Helvetica, Arial, sans-serif" font-weight="400" fill="{overlay_style.door_color}">x {door_count}</text>',
            ]
        )
    if stair_enabled and stair_count > 0:
        overlay_parts.extend(
            [
                f'  <line x1="41.0" y1="38.6" x2="41.0" y2="33.6" stroke="{overlay_style.stair_color}" stroke-width="0.28"/>',
                f'  <path d="M 39.9 34.7 L 41.0 33.0 L 42.1 34.7 Z" fill="{overlay_style.stair_color}" stroke="none"/>',
                f'  <text x="42.4" y="34.4" font-size="2.3" font-family="Helvetica, Arial, sans-serif" font-weight="700" fill="{overlay_style.stair_color}">{stair_label}</text>',
                f'  <text x="47.8" y="34.4" font-size="2.6" font-family="Helvetica, Arial, sans-serif" font-weight="400" fill="{overlay_style.stair_color}">x {stair_count}</text>',
            ]
        )
    if room_enabled and room_count > 0:
        overlay_parts.extend(
            [
                f'  <rect x="57.8" y="36.1" width="8.4" height="4.8" fill="{overlay_style.room_fill_color}" stroke="{overlay_style.room_stroke_color}" stroke-width="0.22" rx="0.7" ry="0.7"/>',
                f'  <text x="59.0" y="39.5" font-size="2.2" font-family="Helvetica, Arial, sans-serif" font-weight="700" fill="{overlay_style.room_text_color}">{room_preview}</text>',
                f'  <text x="67.3" y="39.4" font-size="2.6" font-family="Helvetica, Arial, sans-serif" font-weight="400" fill="{overlay_style.room_text_color}">x {room_count}</text>',
            ]
        )
    if not has_existing_view_overlay:
        overlay_parts.extend(_render_replay_view_symbols(view_overlay, overlay_style))
    overlay = "\n".join(overlay_parts) + "\n"
    text = text.replace(marker, overlay + marker, 1)
    svg_path.write_text(text, encoding="utf-8")


def _feature_count_token(enabled: bool, count: int) -> str:
    return str(count) if enabled else "off"


def _room_preview_label(overlay_style: FeatureOverlayRule) -> str:
    mode = overlay_style.room_label_mode.strip().lower()
    if mode == "fixed":
        label = overlay_style.room_fixed_label.strip() or "ROOM"
    else:
        label = overlay_style.room_label_prefix.strip() or "R"
    return label[:3]


def _build_view_overlay_by_sheet(bundle_dir: Path) -> dict:
    view_manifest = _load_optional_json(bundle_dir / "metadata" / "view_manifest.json")
    view_geometry = _load_optional_json(bundle_dir / "metadata" / "view_geometry.json")
    if not isinstance(view_manifest, list) or not isinstance(view_geometry, list):
        return {}

    geometry_by_view_id = {}
    for item in view_geometry:
        if not isinstance(item, dict):
            continue
        view_id = str(item.get("view_id", ""))
        if not view_id:
            continue
        geometry_by_view_id[view_id] = item

    by_sheet: dict = {}
    for view in view_manifest:
        if not isinstance(view, dict):
            continue
        view_id = str(view.get("view_id", ""))
        sheet_id = str(view.get("sheet_id", ""))
        if not view_id or not sheet_id:
            continue
        geometry = geometry_by_view_id.get(view_id)
        if not isinstance(geometry, dict):
            continue
        anchors = geometry.get("feature_anchors", [])
        bounds = geometry.get("bounds")
        if not isinstance(anchors, list) or not isinstance(bounds, dict):
            continue
        by_sheet[sheet_id] = {"feature_anchors": anchors, "bounds": bounds}
    return by_sheet


def _render_replay_view_symbols(view_overlay: dict | None, overlay_style: FeatureOverlayRule) -> List[str]:
    if not isinstance(view_overlay, dict):
        return []
    anchors = view_overlay.get("feature_anchors")
    bounds = view_overlay.get("bounds")
    if not isinstance(anchors, list) or not isinstance(bounds, dict):
        return []
    transform = _build_replay_transform(bounds)
    if transform is None:
        return []

    buckets = {"IfcDoor": [], "IfcStair": [], "IfcSpace": []}
    for item in anchors:
        if not isinstance(item, dict):
            continue
        class_name = str(item.get("ifc_class", ""))
        anchor = item.get("anchor")
        if class_name not in buckets or not isinstance(anchor, dict):
            continue
        try:
            x = float(anchor.get("x"))
            y = float(anchor.get("y"))
        except Exception:
            continue
        source = str(item.get("source_element", ""))
        label = str(item.get("label", "") or "")
        buckets[class_name].append(
            {
                "x": x,
                "y": y,
                "dir_x": float(item.get("dir_x", 1.0) or 1.0),
                "dir_y": float(item.get("dir_y", 0.0) or 0.0),
                "source_element": source,
                "label": label,
            }
        )
    for key in buckets:
        buckets[key].sort(key=lambda item: (item["source_element"], item["y"], item["x"]))

    lines: List[str] = []
    if overlay_style.doors_enabled:
        for item in buckets["IfcDoor"][: max(0, int(overlay_style.max_door_markers))]:
            sx, sy = transform(item["x"], item["y"])
            ux, uy = _normalize_2d(item["dir_x"], item["dir_y"])
            label = overlay_style.door_label.strip() or "D"
            lines.extend(_replay_door_symbol(sx, sy, ux, uy, overlay_style.door_color, label))
    if overlay_style.stairs_enabled:
        for item in buckets["IfcStair"][: max(0, int(overlay_style.max_stair_arrows))]:
            sx, sy = transform(item["x"], item["y"])
            ux, uy = _normalize_2d(item["dir_x"], item["dir_y"])
            label = overlay_style.stair_label.strip() or "UP"
            lines.extend(_replay_stair_symbol(sx, sy, ux, uy, overlay_style.stair_color, label))
    if overlay_style.rooms_enabled:
        for item in buckets["IfcSpace"][: max(0, int(overlay_style.max_room_tags))]:
            sx, sy = transform(item["x"], item["y"])
            label = item["label"] or _room_preview_label(overlay_style)
            lines.extend(
                _replay_room_symbol(
                    sx,
                    sy,
                    label,
                    overlay_style.room_fill_color,
                    overlay_style.room_stroke_color,
                    overlay_style.room_text_color,
                )
            )
    return lines


def _build_replay_transform(bounds: dict):
    try:
        min_x = float(bounds.get("min_x"))
        min_y = float(bounds.get("min_y"))
        max_x = float(bounds.get("max_x"))
        max_y = float(bounds.get("max_y"))
    except Exception:
        return None
    world_width = max(max_x - min_x, 1.0e-6)
    world_height = max(max_y - min_y, 1.0e-6)
    x = 20.0
    y = 38.0
    width = 170.0
    height = 150.0
    padding = 4.0
    usable_width = width - padding * 2.0
    usable_height = height - padding * 2.0
    scale = min(usable_width / world_width, usable_height / world_height)
    x_offset = x + padding + (usable_width - world_width * scale) / 2.0
    y_offset = y + padding + (usable_height - world_height * scale) / 2.0

    def transform(px: float, py: float):
        sx = x_offset + (px - min_x) * scale
        sy = y_offset + (max_y - py) * scale
        return round(sx, 3), round(sy, 3)

    return transform


def _normalize_2d(x: float, y: float):
    length = math.hypot(x, y)
    if length <= 1.0e-9:
        return 1.0, 0.0
    return x / length, y / length


def _replay_door_symbol(sx: float, sy: float, ux: float, uy: float, color: str, label: str) -> List[str]:
    leaf = 2.6
    ex = sx + ux * leaf
    ey = sy + uy * leaf
    return [
        f'  <circle cx="{round(sx, 3)}" cy="{round(sy, 3)}" r="0.75" fill="#ffffff" stroke="{color}" stroke-width="0.18"/>',
        f'  <line x1="{round(sx, 3)}" y1="{round(sy, 3)}" x2="{round(ex, 3)}" y2="{round(ey, 3)}" stroke="{color}" stroke-width="0.18"/>',
        f'  <text x="{round(sx - 0.5, 3)}" y="{round(sy + 0.8, 3)}" font-size="1.8" font-family="Helvetica, Arial, sans-serif" font-weight="700" fill="{color}">{label}</text>',
    ]


def _replay_stair_symbol(sx: float, sy: float, ux: float, uy: float, color: str, label: str) -> List[str]:
    half = 2.4
    start_x = sx - ux * half
    start_y = sy - uy * half
    end_x = sx + ux * half
    end_y = sy + uy * half
    return [
        f'  <line x1="{round(start_x, 3)}" y1="{round(start_y, 3)}" x2="{round(end_x, 3)}" y2="{round(end_y, 3)}" stroke="{color}" stroke-width="0.2"/>',
        f'  <text x="{round(end_x + 0.8, 3)}" y="{round(end_y + 0.6, 3)}" font-size="1.8" font-family="Helvetica, Arial, sans-serif" font-weight="700" fill="{color}">{label}</text>',
    ]


def _replay_room_symbol(
    sx: float,
    sy: float,
    label: str,
    fill_color: str,
    stroke_color: str,
    text_color: str,
) -> List[str]:
    half_w = max(2.4, 0.9 + len(label) * 0.45)
    half_h = 1.5
    x = sx - half_w
    y = sy - half_h
    return [
        f'  <rect x="{round(x, 3)}" y="{round(y, 3)}" width="{round(half_w * 2.0, 3)}" height="{round(half_h * 2.0, 3)}" fill="{fill_color}" stroke="{stroke_color}" stroke-width="0.16" rx="0.45" ry="0.45"/>',
        f'  <text x="{round(sx - (len(label) * 0.45) / 2.0, 3)}" y="{round(sy + 0.55, 3)}" font-size="1.6" font-family="Helvetica, Arial, sans-serif" font-weight="700" fill="{text_color}">{label[:18]}</text>',
    ]
