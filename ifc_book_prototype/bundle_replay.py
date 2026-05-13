from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import List

from .domain import (
    Bounds2D,
    FeatureAnchor2D,
    FeatureOverlayRule,
    GeometrySummary,
    LineKind,
    LineweightClass,
    NormalizedModel,
    PipelineManifest,
    PlannedView,
    Point2D,
    ScheduleRow,
    ScheduleSheet,
    SheetArtifact,
    StoreySummary,
    StyleProfile,
    TypedLine2D,
    TypedRegion2D,
    ViewLinework,
    to_primitive,
)
from .geometry_metrics import summarize_geometry_runtime
from .pipeline import STAGE_ARTIFACTS, _build_cache_manifest, _slugify, _stable_hash
from .render_pdf import write_pdf_from_svg_sheets
from .render_svg import (
    _room_tag_symbol,
    _stair_symbol,
    render_cover_svg,
    render_index_svg,
    render_schedule_svg,
    render_view_svg,
)


METADATA_FILENAMES = (
    "preflight.json",
    "normalized_model.json",
    "view_manifest.json",
    "view_geometry.json",
    "view_linework.json",
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


def replay_bundle(
    bundle_dir: Path,
    output_dir: Path,
    profile: StyleProfile | None = None,
    *,
    rerender_linework: bool = False,
) -> PipelineManifest:
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
    replay_stair_count = int(source_counts.get("IFCSTAIR", 0) or 0)
    replay_room_count = int(source_counts.get("IFCSPACE", 0) or 0)
    overlay_style = profile.floor_plan.feature_overlay if profile is not None else FeatureOverlayRule()
    overlay_by_sheet = _build_view_overlay_by_sheet(bundle_dir)

    replay_mode = "copy"
    copied_sheets: List[SheetArtifact] | None = None
    rerendered_view_count = 0
    if rerender_linework:
        try:
            copied_sheets = _rerender_bundle_from_linework(
                bundle_dir=bundle_dir,
                sheets_dir=sheets_dir,
                source_manifest=source_manifest,
                profile=profile,
            )
            replay_mode = "rerender_linework"
            rerendered_view_count = len([sheet for sheet in copied_sheets if sheet.role == "view"])
        except ValueError as exc:
            warnings.append(f"Typed linework rerender unavailable: {exc!s}")

    if copied_sheets is None:
        copied_sheets = []
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

    linework_artifact = _load_optional_json(metadata_dir / "view_linework.json")
    if linework_artifact is None:
        linework_artifact = _empty_linework_artifact()
        (metadata_dir / "view_linework.json").write_text(
            json.dumps(linework_artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    bundle_summary = _build_bundle_summary(
        bundle_dir,
        source_manifest,
        copied_sheets,
        replay_mode=replay_mode,
        rerendered_view_count=rerendered_view_count,
    )
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

    manifest_style_profile_id = (
        profile.profile_id if profile is not None and replay_mode == "rerender_linework"
        else source_manifest["style_profile_id"]
    )
    manifest_job_id = source_manifest["job_id"]
    if replay_mode == "rerender_linework":
        manifest_job_id = _stable_hash(
            {
                "input_sha256": source_manifest["input_sha256"],
                "profile_id": manifest_style_profile_id,
                "model_hash": source_manifest["model_hash"],
            }
        )[:12]
    cache = _build_cache_manifest(
        input_sha256=source_manifest["input_sha256"],
        style_profile_id=manifest_style_profile_id,
        model_hash=source_manifest["model_hash"],
        linework_artifact=linework_artifact or _empty_linework_artifact(),
    )
    cache["replay"] = {
        "mode": replay_mode,
        "rerendered_view_count": rerendered_view_count,
        "source_bundle_dir": str(bundle_dir),
    }
    manifest = PipelineManifest(
        job_id=manifest_job_id,
        input_sha256=source_manifest["input_sha256"],
        style_profile_id=manifest_style_profile_id,
        model_hash=source_manifest["model_hash"],
        output_dir=str(output_dir),
        pdf_path=copied_pdf_path,
        sheets=copied_sheets,
        warnings=warnings,
        stage_artifacts=dict(STAGE_ARTIFACTS),
        cache=cache,
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


def _build_bundle_summary(
    bundle_dir: Path,
    source_manifest: dict,
    copied_sheets: List[SheetArtifact],
    *,
    replay_mode: str = "copy",
    rerendered_view_count: int = 0,
) -> dict:
    preflight = _load_optional_json(bundle_dir / "metadata" / "preflight.json")
    normalized = _load_optional_json(bundle_dir / "metadata" / "normalized_model.json")
    view_manifest = _load_optional_json(bundle_dir / "metadata" / "view_manifest.json") or []
    schedule_manifest = _load_optional_json(bundle_dir / "metadata" / "schedule_manifest.json") or []
    geometry_runtime_summary = _load_optional_json(bundle_dir / "metadata" / "geometry_runtime_summary.json")
    view_linework = _load_optional_json(bundle_dir / "metadata" / "view_linework.json")
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
        "replay": {
            "mode": replay_mode,
            "rerendered_view_count": rerendered_view_count,
        },
        "schedule_categories": sorted({sheet.get("category", "") for sheet in schedule_manifest if sheet.get("category")}),
        "storey_count": len((normalized or {}).get("storeys", [])),
        "view_titles": [view.get("title", "") for view in view_manifest],
        "geometry_runtime_summary": geometry_runtime_summary,
        "linework_summary": (view_linework or {}).get("summary", {}),
        "capability_counts": capability_counts,
        "capabilities": {
            "has_spaces": capability_counts["IFCSPACE"] > 0,
            "has_openings": capability_counts["IFCDOOR"] > 0 or capability_counts["IFCWINDOW"] > 0,
            "has_circulation": capability_counts["IFCSTAIR"] > 0 or capability_counts["IFCRAMP"] > 0,
            "has_structural_types": any(capability_counts[name] > 0 for name in ("IFCCOLUMN", "IFCBEAM", "IFCMEMBER", "IFCSLAB")),
        },
    }


def _rerender_bundle_from_linework(
    *,
    bundle_dir: Path,
    sheets_dir: Path,
    source_manifest: dict,
    profile: StyleProfile | None,
) -> List[SheetArtifact]:
    if profile is None:
        raise ValueError("a style profile is required.")

    normalized_raw = _load_optional_json(bundle_dir / "metadata" / "normalized_model.json")
    view_manifest_raw = _load_optional_json(bundle_dir / "metadata" / "view_manifest.json")
    view_linework_raw = _load_optional_json(bundle_dir / "metadata" / "view_linework.json")
    schedule_manifest_raw = _load_optional_json(bundle_dir / "metadata" / "schedule_manifest.json") or []
    view_geometry_raw = _load_optional_json(bundle_dir / "metadata" / "view_geometry.json") or []
    if not isinstance(normalized_raw, dict):
        raise ValueError("metadata/normalized_model.json is missing or invalid.")
    if not isinstance(view_manifest_raw, list):
        raise ValueError("metadata/view_manifest.json is missing or invalid.")
    if not _linework_artifact_has_typed_lines(view_linework_raw):
        raise ValueError("metadata/view_linework.json has no typed linework.")

    model = _normalized_model_from_dict(normalized_raw)
    views = [_planned_view_from_dict(item) for item in view_manifest_raw if isinstance(item, dict)]
    schedules = [
        _schedule_sheet_from_dict(item)
        for item in schedule_manifest_raw
        if isinstance(item, dict)
    ]
    linework_by_view_id = _linework_views_by_id(view_linework_raw)
    geometry_by_view_id = {
        str(item.get("view_id", "")): item
        for item in view_geometry_raw
        if isinstance(item, dict) and item.get("view_id")
    }

    job_id = _stable_hash(
        {
            "input_sha256": source_manifest["input_sha256"],
            "profile_id": profile.profile_id,
            "model_hash": source_manifest["model_hash"],
        }
    )[:12]
    sheet_artifacts: List[SheetArtifact] = []

    cover_svg = render_cover_svg(model, profile, job_id, source_manifest["input_sha256"])
    cover_path = sheets_dir / f"{profile.cover_sheet_id.lower()}_cover.svg"
    cover_path.write_text(cover_svg, encoding="utf-8")
    sheet_artifacts.append(
        SheetArtifact(
            sheet_id=profile.cover_sheet_id,
            title="Cover Sheet",
            svg_path=str(cover_path),
            page_number=1,
            role="cover",
        )
    )

    index_entries = [(sheet.sheet_id, sheet.title) for sheet in sheet_artifacts]
    for view in views:
        index_entries.append((view.sheet_id, view.title))
    for schedule in schedules:
        index_entries.append((schedule.sheet_id, schedule.title))
    index_svg = render_index_svg(index_entries, profile)
    index_path = sheets_dir / f"{profile.index_sheet_id.lower()}_index.svg"
    index_path.write_text(index_svg, encoding="utf-8")
    sheet_artifacts.append(
        SheetArtifact(
            sheet_id=profile.index_sheet_id,
            title="Drawing Index",
            svg_path=str(index_path),
            page_number=2,
            role="index",
        )
    )

    for view in views:
        linework_view = linework_by_view_id.get(view.view_id, {})
        geometry = _geometry_from_cached_view(
            view_id=view.view_id,
            linework_view=linework_view,
            geometry_view=geometry_by_view_id.get(view.view_id, {}),
        )
        svg = render_view_svg(model, view, geometry, profile)
        slug_source = view.storey_name if view.storey_name else view.view_id
        svg_path = sheets_dir / f"{view.sheet_id.lower()}_{_slugify(slug_source)}.svg"
        svg_path.write_text(svg, encoding="utf-8")
        sheet_artifacts.append(
            SheetArtifact(
                sheet_id=view.sheet_id,
                title=view.title,
                svg_path=str(svg_path),
                page_number=len(sheet_artifacts) + 1,
                role="view",
            )
        )

    for schedule in schedules:
        svg = render_schedule_svg(schedule, profile)
        svg_path = sheets_dir / f"{schedule.sheet_id.lower()}_{_slugify(schedule.title)}.svg"
        svg_path.write_text(svg, encoding="utf-8")
        sheet_artifacts.append(
            SheetArtifact(
                sheet_id=schedule.sheet_id,
                title=schedule.title,
                svg_path=str(svg_path),
                page_number=len(sheet_artifacts) + 1,
                role="schedule",
            )
        )

    return sheet_artifacts


def _linework_artifact_has_typed_lines(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    summary = payload.get("summary", {})
    if isinstance(summary, dict) and int(summary.get("line_count", 0) or 0) > 0:
        return True
    views = payload.get("views", [])
    if not isinstance(views, list):
        return False
    for view in views:
        if not isinstance(view, dict):
            continue
        linework = view.get("linework", {})
        if isinstance(linework, dict) and linework.get("lines"):
            return True
    return False


def _normalized_model_from_dict(payload: dict) -> NormalizedModel:
    return NormalizedModel(
        model_hash=str(payload.get("model_hash", "")),
        project_name=str(payload.get("project_name", "")),
        building_name=str(payload.get("building_name", "")),
        schema=str(payload.get("schema", "")),
        source_scanner=str(payload.get("source_scanner", "")),
        storeys=[
            StoreySummary(
                index=int(item.get("index", 0) or 0),
                name=str(item.get("name", "")),
                elevation_m=_optional_float(item.get("elevation_m")),
            )
            for item in payload.get("storeys", [])
            if isinstance(item, dict)
        ],
        space_count=int(payload.get("space_count", 0) or 0),
        supported_class_counts={
            str(key): int(value or 0)
            for key, value in (payload.get("supported_class_counts", {}) or {}).items()
        },
        warnings=[str(item) for item in payload.get("warnings", [])],
    )


def _planned_view_from_dict(payload: dict) -> PlannedView:
    return PlannedView(
        view_id=str(payload.get("view_id", "")),
        sheet_id=str(payload.get("sheet_id", "")),
        title=str(payload.get("title", "")),
        storey_name=str(payload.get("storey_name", "")),
        storey_elevation_m=_optional_float(payload.get("storey_elevation_m")),
        cut_plane_m=float(payload.get("cut_plane_m", 0.0) or 0.0),
        view_depth_below_m=float(payload.get("view_depth_below_m", 0.0) or 0.0),
        overhead_depth_above_m=float(payload.get("overhead_depth_above_m", 0.0) or 0.0),
        included_classes=[str(item) for item in payload.get("included_classes", [])],
        view_kind=str(payload.get("view_kind", "plan")),
    )


def _schedule_sheet_from_dict(payload: dict) -> ScheduleSheet:
    return ScheduleSheet(
        schedule_id=str(payload.get("schedule_id", "")),
        sheet_id=str(payload.get("sheet_id", "")),
        title=str(payload.get("title", "")),
        category=str(payload.get("category", "")),
        label_header=str(payload.get("label_header", "")),
        rows=[
            ScheduleRow(
                ifc_class=str(row.get("ifc_class", "")),
                label=str(row.get("label", "")),
                storey_name=str(row.get("storey_name", "")),
                count=int(row.get("count", 0) or 0),
            )
            for row in payload.get("rows", [])
            if isinstance(row, dict)
        ],
        notes=[str(item) for item in payload.get("notes", [])],
    )


def _linework_views_by_id(payload: dict) -> dict:
    result: dict = {}
    for item in payload.get("views", []):
        if not isinstance(item, dict):
            continue
        view_id = str(item.get("view_id", ""))
        if view_id:
            result[view_id] = item
    return result


def _geometry_from_cached_view(
    *,
    view_id: str,
    linework_view: dict,
    geometry_view: dict,
) -> GeometrySummary:
    linework = _view_linework_from_dict(linework_view.get("linework", {}))
    linework_counts = _int_dict(
        linework_view.get("linework_counts")
        or geometry_view.get("linework_counts")
        or linework.counts_by_kind
    )
    bounds = _bounds_from_dict(linework_view.get("bounds") or geometry_view.get("bounds"))
    feature_anchors = [
        _feature_anchor_from_dict(item)
        for item in geometry_view.get("feature_anchors", [])
        if isinstance(item, dict)
    ]
    return GeometrySummary(
        view_id=view_id,
        backend=str(geometry_view.get("backend") or linework_view.get("backend") or "typed-linework-replay"),
        cut_candidates=_int_dict(geometry_view.get("cut_candidates", {})),
        projection_candidates=_int_dict(geometry_view.get("projection_candidates", {})),
        source_elements=int(geometry_view.get("source_elements", 0) or 0),
        path_count=int(geometry_view.get("path_count", len(linework.lines)) or 0),
        bounds=bounds,
        notes=_replay_notes(geometry_view.get("notes", [])),
        linework=linework,
        linework_counts=linework_counts,
        owned_geometry_telemetry=dict(geometry_view.get("owned_geometry_telemetry", {}) or {}),
        feature_anchors=feature_anchors,
        feature_anchor_counts=_int_dict(geometry_view.get("feature_anchor_counts", {})),
        fallback_events=int(geometry_view.get("fallback_events", 0) or 0),
        fallback_by_class=_int_dict(geometry_view.get("fallback_by_class", {})),
        fallback_timeout_events=int(geometry_view.get("fallback_timeout_events", 0) or 0),
        fallback_exception_events=int(geometry_view.get("fallback_exception_events", 0) or 0),
        fallback_empty_events=int(geometry_view.get("fallback_empty_events", 0) or 0),
    )


def _view_linework_from_dict(payload) -> ViewLinework:
    if not isinstance(payload, dict):
        payload = {}
    return ViewLinework(
        lines=[
            _typed_line_from_dict(item)
            for item in payload.get("lines", [])
            if isinstance(item, dict)
        ],
        regions=[
            _typed_region_from_dict(item)
            for item in payload.get("regions", [])
            if isinstance(item, dict)
        ],
        quantization_m=float(payload.get("quantization_m", 1.0e-5) or 1.0e-5),
        counts_by_kind=_int_dict(payload.get("counts_by_kind", {})),
    )


def _typed_line_from_dict(payload: dict) -> TypedLine2D:
    return TypedLine2D(
        kind=_line_kind(payload.get("kind")),
        lineweight_class=_lineweight_class(payload.get("lineweight_class")),
        points=[
            _point_from_dict(item)
            for item in payload.get("points", [])
            if isinstance(item, dict)
        ],
        closed=bool(payload.get("closed", False)),
        source_element=_optional_str(payload.get("source_element")),
        source_ifc_class=_optional_str(payload.get("source_ifc_class")),
        z_order_hint=int(payload.get("z_order_hint", 0) or 0),
        notes=tuple(str(item) for item in payload.get("notes", [])),
    )


def _typed_region_from_dict(payload: dict) -> TypedRegion2D:
    return TypedRegion2D(
        kind=_line_kind(payload.get("kind")),
        rings=[
            [
                _point_from_dict(point)
                for point in ring
                if isinstance(point, dict)
            ]
            for ring in payload.get("rings", [])
            if isinstance(ring, list)
        ],
        source_element=_optional_str(payload.get("source_element")),
        source_ifc_class=_optional_str(payload.get("source_ifc_class")),
    )


def _feature_anchor_from_dict(payload: dict) -> FeatureAnchor2D:
    anchor = payload.get("anchor", {})
    if not isinstance(anchor, dict):
        anchor = {}
    return FeatureAnchor2D(
        ifc_class=str(payload.get("ifc_class", "")),
        anchor=_point_from_dict(anchor),
        dir_x=float(payload.get("dir_x", 1.0) or 1.0),
        dir_y=float(payload.get("dir_y", 0.0) or 0.0),
        source_element=_optional_str(payload.get("source_element")),
        display_label=_optional_str(payload.get("display_label")),
        door_handedness=_optional_str(payload.get("door_handedness")),
        operation_type=_optional_str(payload.get("operation_type")),
        semantic_source=_optional_str(payload.get("semantic_source")),
        semantic_confidence=_optional_float(payload.get("semantic_confidence")),
        host_element=_optional_str(payload.get("host_element")),
        label=_optional_str(payload.get("label")),
        width_m=_optional_float(payload.get("width_m")),
    )


def _bounds_from_dict(payload) -> Bounds2D | None:
    if not isinstance(payload, dict):
        return None
    try:
        return Bounds2D(
            min_x=float(payload.get("min_x")),
            min_y=float(payload.get("min_y")),
            max_x=float(payload.get("max_x")),
            max_y=float(payload.get("max_y")),
        )
    except (TypeError, ValueError):
        return None


def _point_from_dict(payload: dict) -> Point2D:
    return Point2D(
        x=float(payload.get("x", 0.0) or 0.0),
        y=float(payload.get("y", 0.0) or 0.0),
    )


def _line_kind(value) -> LineKind:
    key = str(value or "PROJECTED")
    return LineKind.__members__.get(key, LineKind.PROJECTED)


def _lineweight_class(value) -> LineweightClass:
    key = str(value or "LIGHT")
    return LineweightClass.__members__.get(key, LineweightClass.LIGHT)


def _int_dict(payload) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    return {str(key): int(value or 0) for key, value in payload.items()}


def _optional_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _replay_notes(notes) -> list[str]:
    result = [str(item) for item in notes] if isinstance(notes, list) else []
    result.append("Replay source: cached typed linework.")
    return result


def _empty_linework_artifact() -> dict:
    return {
        "schema_version": 1,
        "views": [],
        "summary": {
            "view_count": 0,
            "typed_view_count": 0,
            "line_count": 0,
            "region_count": 0,
        },
    }


def _load_optional_json(path: Path):
    if not path.exists():
        return None
    return _load_json(path)


def _inject_replay_feature_overlay(
    svg_path: Path,
    stair_count: int,
    room_count: int = 0,
    overlay_style: FeatureOverlayRule | None = None,
    view_overlay: dict | None = None,
) -> None:
    overlay_style = overlay_style or FeatureOverlayRule()
    if not overlay_style.enabled:
        return
    if stair_count <= 0 and room_count <= 0:
        return
    text = svg_path.read_text(encoding="utf-8")
    marker = "</svg>"
    if marker not in text:
        return
    has_existing_view_overlay = "Feature overlay |" in text
    stair_enabled = bool(overlay_style.stairs_enabled)
    room_enabled = bool(overlay_style.rooms_enabled)
    stair_label = overlay_style.stair_label.strip() or "UP"
    room_preview = _room_preview_label(overlay_style)
    overlay_parts = [
        f'  <text x="22.0" y="33.0" font-size="2.8" font-family="Helvetica, Arial, sans-serif" font-weight="400" fill="{overlay_style.legend_color}">'
        f"Replay feature overlay | Stairs: {_feature_count_token(stair_enabled, stair_count)} | Rooms: {_feature_count_token(room_enabled, room_count)}"
        "</text>",
    ]
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

    buckets = {"IfcStair": [], "IfcSpace": []}
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
        display_label = str(item.get("display_label", "") or "")
        buckets[class_name].append(
            {
                "x": x,
                "y": y,
                "dir_x": float(item.get("dir_x", 1.0) or 1.0),
                "dir_y": float(item.get("dir_y", 0.0) or 0.0),
                "source_element": source,
                "label": label,
                "display_label": display_label,
            }
        )
    for key in buckets:
        buckets[key].sort(key=lambda item: (item["source_element"], item["y"], item["x"]))

    lines: List[str] = []
    if overlay_style.stairs_enabled:
        for item in buckets["IfcStair"][: max(0, int(overlay_style.max_stair_arrows))]:
            sx, sy = transform(item["x"], item["y"])
            ux, uy = _normalize_2d(item["dir_x"], item["dir_y"])
            label = overlay_style.stair_label.strip() or "UP"
            lines.extend(_stair_symbol(sx, sy, ux, uy, overlay_style.stair_color, label))
    if overlay_style.rooms_enabled:
        for item in buckets["IfcSpace"][: max(0, int(overlay_style.max_room_tags))]:
            sx, sy = transform(item["x"], item["y"])
            label = item["display_label"] or item["label"] or _room_preview_label(overlay_style)
            lines.extend(
                _room_tag_symbol(
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
