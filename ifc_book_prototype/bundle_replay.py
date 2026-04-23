from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import List

from .domain import PipelineManifest, SheetArtifact, to_primitive
from .render_pdf import write_pdf_from_svg_sheets


METADATA_FILENAMES = (
    "preflight.json",
    "normalized_model.json",
    "view_manifest.json",
    "view_geometry.json",
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


def replay_bundle(bundle_dir: Path, output_dir: Path) -> PipelineManifest:
    bundle_dir = bundle_dir.resolve()
    output_dir = output_dir.resolve()
    metadata_dir = output_dir / "metadata"
    sheets_dir = output_dir / "sheets"
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(exist_ok=True)
    sheets_dir.mkdir(exist_ok=True)

    source_manifest = _load_json(bundle_dir / "manifest.json")
    warnings = list(source_manifest.get("warnings", []))

    copied_sheets: List[SheetArtifact] = []
    for sheet in source_manifest.get("sheets", []):
        source_svg = _resolve_source_path(bundle_dir, sheet.get("svg_path", ""), bundle_dir / "sheets")
        if source_svg is None:
            warnings.append(f"Missing source sheet SVG for {sheet.get('sheet_id', 'unknown')}.")
            continue
        destination_svg = sheets_dir / source_svg.name
        shutil.copy2(source_svg, destination_svg)
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
