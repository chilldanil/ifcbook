from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import List

from .domain import (
    GeometrySummary,
    NormalizedModel,
    PipelineManifest,
    PlannedView,
    PreflightReport,
    ScheduleSheet,
    SheetArtifact,
    StoreySummary,
    StyleProfile,
    to_primitive,
)
from .geometry_backend import create_geometry_backend
from .ifc_loader import IfcScan, scan_ifc
from .render_pdf import write_pdf_from_svg_sheets
from .render_svg import render_cover_svg, render_index_svg, render_schedule_svg, render_view_svg
from .schedules import extract_schedule_sheets


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(obj) -> str:
    payload = json.dumps(to_primitive(obj), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(payload)


def _slugify(value: str) -> str:
    chars = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        elif chars and chars[-1] != "_":
            chars.append("_")
    return "".join(chars).strip("_") or "sheet"


class PrototypePipeline:
    def __init__(self, profile: StyleProfile):
        self.profile = profile

    def run(self, ifc_path: Path, output_dir: Path) -> PipelineManifest:
        output_dir.mkdir(parents=True, exist_ok=True)
        metadata_dir = output_dir / "metadata"
        sheets_dir = output_dir / "sheets"
        metadata_dir.mkdir(exist_ok=True)
        sheets_dir.mkdir(exist_ok=True)

        preflight, scan = self._preflight(ifc_path)
        normalized = self._normalize(scan, preflight)
        views = self._plan_views(normalized)
        geometry_backend = create_geometry_backend(
            ifc_path,
            self.profile.floor_plan.include_classes,
            profile=self.profile,
        )
        geometry = [geometry_backend.build_view(view) for view in views]
        schedules = extract_schedule_sheets(ifc_path, self.profile.sheet_prefix)
        manifest = self._render(output_dir, metadata_dir, sheets_dir, preflight, normalized, views, geometry, schedules)

        self._write_json(metadata_dir / "preflight.json", preflight)
        self._write_json(metadata_dir / "normalized_model.json", normalized)
        self._write_json(metadata_dir / "view_manifest.json", views)
        self._write_json(metadata_dir / "view_geometry.json", geometry)
        self._write_json(metadata_dir / "schedule_manifest.json", schedules)
        self._write_json(output_dir / "manifest.json", manifest)
        return manifest

    def _preflight(self, ifc_path: Path) -> tuple[PreflightReport, IfcScan]:
        input_sha256 = _sha256_file(ifc_path)
        scan = scan_ifc(ifc_path)
        warnings = list(scan.warnings)
        if not scan.entity_counts:
            warnings.append("No IFC entities were detected in the SPF data section.")
        report = PreflightReport(
            input_path=str(ifc_path.resolve()),
            input_sha256=input_sha256,
            size_bytes=ifc_path.stat().st_size,
            schema=scan.schema,
            scanner=scan.scanner,
            entity_counts=scan.entity_counts,
            warnings=warnings,
        )
        return report, scan

    def _normalize(self, scan: IfcScan, preflight: PreflightReport) -> NormalizedModel:
        storeys = [
            StoreySummary(index=index, name=name, elevation_m=elevation_m)
            for index, (name, elevation_m) in enumerate(scan.storeys, start=1)
        ]
        warnings = list(preflight.warnings)
        if not storeys:
            storeys = [StoreySummary(index=1, name="Unpartitioned Building View", elevation_m=0.0)]
            warnings.append("No IfcBuildingStorey entities were found; created a synthetic single view.")

        supported_counts = {
            name: scan.entity_counts.get(name.upper(), 0)
            for name in self.profile.floor_plan.include_classes
        }
        identity = {
            "schema": scan.schema,
            "project_name": scan.project_name,
            "building_name": scan.building_name,
            "storeys": [to_primitive(storey) for storey in storeys],
            "supported_counts": supported_counts,
            "space_count": scan.space_count,
            "scanner": scan.scanner,
        }
        return NormalizedModel(
            model_hash=_stable_hash(identity),
            project_name=scan.project_name,
            building_name=scan.building_name,
            schema=scan.schema,
            source_scanner=scan.scanner,
            storeys=storeys,
            space_count=scan.space_count,
            supported_class_counts=supported_counts,
            warnings=warnings,
        )

    def _plan_views(self, model: NormalizedModel) -> List[PlannedView]:
        views: List[PlannedView] = []
        start_sheet_number = 101
        for offset, storey in enumerate(model.storeys):
            sheet_id = f"{self.profile.sheet_prefix}-{start_sheet_number + offset:03d}"
            view_id = f"floor_plan_{storey.index:02d}"
            views.append(
                PlannedView(
                    view_id=view_id,
                    sheet_id=sheet_id,
                    title=f"Floor Plan - {storey.name}",
                    storey_name=storey.name,
                    storey_elevation_m=storey.elevation_m,
                    cut_plane_m=self.profile.floor_plan.cut_plane_m,
                    view_depth_below_m=self.profile.floor_plan.view_depth_below_m,
                    overhead_depth_above_m=self.profile.floor_plan.overhead_depth_above_m,
                    included_classes=list(self.profile.floor_plan.include_classes),
                )
            )
        return views

    def _render(
        self,
        output_dir: Path,
        metadata_dir: Path,
        sheets_dir: Path,
        preflight: PreflightReport,
        model: NormalizedModel,
        views: List[PlannedView],
        geometry: List[GeometrySummary],
        schedules: List[ScheduleSheet],
    ) -> PipelineManifest:
        job_id = _stable_hash(
            {
                "input_sha256": preflight.input_sha256,
                "profile_id": self.profile.profile_id,
                "model_hash": model.model_hash,
            }
        )[:12]
        sheet_artifacts: List[SheetArtifact] = []

        cover_svg = render_cover_svg(model, self.profile, job_id, preflight.input_sha256)
        cover_path = sheets_dir / f"{self.profile.cover_sheet_id.lower()}_cover.svg"
        cover_path.write_text(cover_svg, encoding="utf-8")
        sheet_artifacts.append(
            SheetArtifact(
                sheet_id=self.profile.cover_sheet_id,
                title="Cover Sheet",
                svg_path=str(cover_path.resolve()),
                page_number=1,
                role="cover",
            )
        )

        index_entries = [(sheet.sheet_id, sheet.title) for sheet in sheet_artifacts]
        for view in views:
            index_entries.append((view.sheet_id, view.title))
        for schedule in schedules:
            index_entries.append((schedule.sheet_id, schedule.title))

        index_svg = render_index_svg(index_entries, self.profile)
        index_path = sheets_dir / f"{self.profile.index_sheet_id.lower()}_index.svg"
        index_path.write_text(index_svg, encoding="utf-8")
        sheet_artifacts.append(
            SheetArtifact(
                sheet_id=self.profile.index_sheet_id,
                title="Drawing Index",
                svg_path=str(index_path.resolve()),
                page_number=2,
                role="index",
            )
        )

        for view, view_geometry in zip(views, geometry):
            svg = render_view_svg(model, view, view_geometry, self.profile)
            svg_path = sheets_dir / f"{view.sheet_id.lower()}_{_slugify(view.storey_name)}.svg"
            svg_path.write_text(svg, encoding="utf-8")
            sheet_artifacts.append(
                SheetArtifact(
                    sheet_id=view.sheet_id,
                    title=view.title,
                    svg_path=str(svg_path.resolve()),
                    page_number=len(sheet_artifacts) + 1,
                    role="view",
                )
            )

        for schedule in schedules:
            svg = render_schedule_svg(schedule, self.profile)
            svg_path = sheets_dir / f"{schedule.sheet_id.lower()}_{_slugify(schedule.title)}.svg"
            svg_path.write_text(svg, encoding="utf-8")
            sheet_artifacts.append(
                SheetArtifact(
                    sheet_id=schedule.sheet_id,
                    title=schedule.title,
                    svg_path=str(svg_path.resolve()),
                    page_number=len(sheet_artifacts) + 1,
                    role="schedule",
                )
            )

        pdf_path = output_dir / "book.pdf"
        ordered_sheet_paths = [
            Path(sheet.svg_path)
            for sheet in sorted(sheet_artifacts, key=lambda sheet: sheet.page_number)
        ]
        write_pdf_from_svg_sheets(pdf_path, ordered_sheet_paths)

        warnings = list(model.warnings)
        warnings.extend(preflight.warnings)
        return PipelineManifest(
            job_id=job_id,
            input_sha256=preflight.input_sha256,
            style_profile_id=self.profile.profile_id,
            model_hash=model.model_hash,
            output_dir=str(output_dir.resolve()),
            pdf_path=str(pdf_path.resolve()),
            sheets=sheet_artifacts,
            warnings=warnings,
        )

    @staticmethod
    def _write_json(path: Path, payload) -> None:
        path.write_text(
            json.dumps(to_primitive(payload), indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
