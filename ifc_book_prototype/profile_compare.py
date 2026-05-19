from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .bundle_replay import replay_bundle
from .domain import PipelineManifest
from .overlay_gate import evaluate_overlay_gate_from_run_dir
from .pipeline import _slugify
from .profiles import load_style_profile


DEFAULT_COMPARE_PROFILES = ("presentation", "permit_set", "coordination")


@dataclass(frozen=True)
class ProfileComparisonItem:
    profile: str
    profile_id: str
    output_dir: Path
    job_id: str
    pdf_path: Path
    pdf_sha256: str
    geometry_sha256: str
    sheet_id: str
    sheet_path: Path
    sheet_sha256: str
    replay_mode: str
    rerendered_view_count: int
    overlay_gate_status: str
    overlay_violation_count: int

    def as_dict(self) -> dict:
        return {
            "profile": self.profile,
            "profile_id": self.profile_id,
            "output_dir": str(self.output_dir),
            "job_id": self.job_id,
            "pdf_path": str(self.pdf_path),
            "pdf_sha256": self.pdf_sha256,
            "geometry_sha256": self.geometry_sha256,
            "sheet_id": self.sheet_id,
            "sheet_path": str(self.sheet_path),
            "sheet_sha256": self.sheet_sha256,
            "replay_mode": self.replay_mode,
            "rerendered_view_count": self.rerendered_view_count,
            "overlay_gate_status": self.overlay_gate_status,
            "overlay_violation_count": self.overlay_violation_count,
        }


@dataclass(frozen=True)
class ProfileComparisonReport:
    bundle_dir: Path
    output_root: Path
    requested_profiles: tuple[str, ...]
    compared_sheet_id: str
    geometry_hashes_match: bool
    sheet_hashes_differ: bool
    pdf_hashes_differ: bool
    items: tuple[ProfileComparisonItem, ...]

    def as_dict(self) -> dict:
        return {
            "bundle_dir": str(self.bundle_dir),
            "output_root": str(self.output_root),
            "requested_profiles": list(self.requested_profiles),
            "compared_sheet_id": self.compared_sheet_id,
            "checks": {
                "geometry_hashes_match": self.geometry_hashes_match,
                "sheet_hashes_differ": self.sheet_hashes_differ,
                "pdf_hashes_differ": self.pdf_hashes_differ,
            },
            "items": [item.as_dict() for item in self.items],
        }


def parse_profile_list(raw: str | None) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return DEFAULT_COMPARE_PROFILES
    profiles = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not profiles:
        raise ValueError("At least one profile is required.")
    return profiles


def compare_profile_rerenders(
    *,
    bundle_dir: Path,
    output_root: Path,
    profiles: Iterable[str] = DEFAULT_COMPARE_PROFILES,
    sheet_id: str | None = None,
) -> ProfileComparisonReport:
    bundle_dir = bundle_dir.resolve()
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    requested_profiles = tuple(profiles)
    if not requested_profiles:
        raise ValueError("At least one profile is required.")

    items = []
    for profile_name in requested_profiles:
        profile = load_style_profile(profile_name)
        profile_output = output_root / _slugify(profile_name)
        manifest = replay_bundle(
            bundle_dir=bundle_dir,
            output_dir=profile_output,
            profile=profile,
            rerender_linework=True,
        )
        items.append(
            _comparison_item_from_manifest(
                profile_name=profile_name,
                manifest=manifest,
                sheet_id=sheet_id,
            )
        )

    geometry_hashes = {item.geometry_sha256 for item in items}
    sheet_hashes = {item.sheet_sha256 for item in items}
    pdf_hashes = {item.pdf_sha256 for item in items}
    compared_sheet_id = items[0].sheet_id if items else (sheet_id or "")
    return ProfileComparisonReport(
        bundle_dir=bundle_dir,
        output_root=output_root,
        requested_profiles=requested_profiles,
        compared_sheet_id=compared_sheet_id,
        geometry_hashes_match=len(geometry_hashes) == 1,
        sheet_hashes_differ=len(sheet_hashes) == len(items),
        pdf_hashes_differ=len(pdf_hashes) == len(items),
        items=tuple(items),
    )


def write_profile_comparison_report(report: ProfileComparisonReport) -> tuple[Path, Path]:
    json_path = report.output_root / "profile_comparison.json"
    markdown_path = report.output_root / "profile_comparison.md"
    json_path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(format_profile_comparison_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def format_profile_comparison_human(report: ProfileComparisonReport) -> str:
    lines = [
        f"PROFILE_COMPARISON bundle_dir={report.bundle_dir}",
        f"output_root={report.output_root}",
        f"compared_sheet_id={report.compared_sheet_id}",
        f"geometry_hashes_match={str(report.geometry_hashes_match).lower()}",
        f"sheet_hashes_differ={str(report.sheet_hashes_differ).lower()}",
        f"pdf_hashes_differ={str(report.pdf_hashes_differ).lower()}",
        "profiles:",
    ]
    for item in report.items:
        lines.append(
            f"  {item.profile}: profile_id={item.profile_id} "
            f"sheet_sha256={item.sheet_sha256[:12]} pdf_sha256={item.pdf_sha256[:12]} "
            f"geometry_sha256={item.geometry_sha256[:12]} "
            f"overlay_gate={item.overlay_gate_status}"
        )
    return "\n".join(lines)


def format_profile_comparison_markdown(report: ProfileComparisonReport) -> str:
    lines = [
        "# Profile Comparison",
        "",
        f"- bundle_dir: {report.bundle_dir}",
        f"- output_root: {report.output_root}",
        f"- compared_sheet_id: {report.compared_sheet_id}",
        f"- geometry_hashes_match: {str(report.geometry_hashes_match).lower()}",
        f"- sheet_hashes_differ: {str(report.sheet_hashes_differ).lower()}",
        f"- pdf_hashes_differ: {str(report.pdf_hashes_differ).lower()}",
        "",
        "| profile | profile_id | overlay_gate | sheet_sha256 | pdf_sha256 | geometry_sha256 | output_dir |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in report.items:
        lines.append(
            "| "
            f"{item.profile} | {item.profile_id} | {item.overlay_gate_status} | {item.sheet_sha256} | "
            f"{item.pdf_sha256} | {item.geometry_sha256} | {item.output_dir} |"
        )
    return "\n".join(lines) + "\n"


def _comparison_item_from_manifest(
    *,
    profile_name: str,
    manifest: PipelineManifest,
    sheet_id: str | None,
) -> ProfileComparisonItem:
    output_dir = Path(manifest.output_dir)
    replay = manifest.cache.get("replay", {}) if isinstance(manifest.cache, dict) else {}
    sheet = _select_compare_sheet(manifest, sheet_id)
    sheet_path = Path(sheet.svg_path)
    pdf_path = Path(manifest.pdf_path)
    geometry_path = output_dir / "metadata" / "view_linework.json"
    overlay_gate = evaluate_overlay_gate_from_run_dir(output_dir)
    return ProfileComparisonItem(
        profile=profile_name,
        profile_id=manifest.style_profile_id,
        output_dir=output_dir,
        job_id=manifest.job_id,
        pdf_path=pdf_path,
        pdf_sha256=_sha256_file(pdf_path),
        geometry_sha256=_sha256_file(geometry_path),
        sheet_id=sheet.sheet_id,
        sheet_path=sheet_path,
        sheet_sha256=_sha256_file(sheet_path),
        replay_mode=str(replay.get("mode", "")),
        rerendered_view_count=int(replay.get("rerendered_view_count", 0) or 0),
        overlay_gate_status="PASS" if overlay_gate.passed else "FAIL",
        overlay_violation_count=overlay_gate.violation_count,
    )


def _select_compare_sheet(manifest: PipelineManifest, sheet_id: str | None):
    sheets = list(manifest.sheets)
    if sheet_id:
        for sheet in sheets:
            if sheet.sheet_id == sheet_id:
                return sheet
        raise ValueError(f"Sheet id not found in rerendered manifest: {sheet_id}")
    for sheet in sheets:
        if sheet.role == "view":
            return sheet
    if sheets:
        return sheets[0]
    raise ValueError("Rerendered manifest contains no sheets.")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
