from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from ifc_book_prototype import bundle_replay
from ifc_book_prototype.domain import (
    Bounds2D,
    GeometrySummary,
    LineKind,
    LineweightClass,
    Point2D,
    TypedLine2D,
    ViewLinework,
)
from ifc_book_prototype.pipeline import _build_cache_manifest, _build_view_linework_artifact
from ifc_book_prototype.profiles import load_style_profile


def test_view_linework_artifact_persists_typed_lines_for_replay():
    geometry = [
        GeometrySummary(
            view_id="floor_plan_01",
            backend="test",
            cut_candidates={"IfcWall": 1},
            projection_candidates={},
            bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=2.0, max_y=1.0),
            linework=ViewLinework(
                lines=[
                    TypedLine2D(
                        kind=LineKind.CUT,
                        lineweight_class=LineweightClass.HEAVY,
                        points=[Point2D(0.0, 0.0), Point2D(2.0, 0.0)],
                        source_element="W1",
                        source_ifc_class="IfcWall",
                    )
                ],
                counts_by_kind={"CUT": 1},
                quantization_m=0.001,
            ),
            linework_counts={"CUT": 1},
        )
    ]

    artifact = _build_view_linework_artifact(geometry)

    assert artifact["summary"] == {
        "view_count": 1,
        "typed_view_count": 1,
        "line_count": 1,
        "region_count": 0,
    }
    view = artifact["views"][0]
    assert view["view_id"] == "floor_plan_01"
    assert view["linework_counts"] == {"CUT": 1}
    assert view["linework"]["quantization_m"] == 0.001
    assert view["linework"]["lines"][0]["kind"] == "CUT"
    assert view["linework"]["lines"][0]["lineweight_class"] == "HEAVY"
    assert view["linework"]["lines"][0]["points"] == [{"x": 0.0, "y": 0.0}, {"x": 2.0, "y": 0.0}]


def test_cache_manifest_references_view_linework_artifact():
    cache = _build_cache_manifest(
        input_sha256="sha",
        style_profile_id="profile",
        model_hash="model",
        linework_artifact={
            "schema_version": 1,
            "summary": {
                "view_count": 2,
                "typed_view_count": 1,
                "line_count": 3,
                "region_count": 4,
            },
        },
    )

    assert cache["schema_version"] == 1
    assert cache["keys"] == {
        "input_sha256": "sha",
        "style_profile_id": "profile",
        "model_hash": "model",
    }
    assert cache["readiness"]["stage_replay"] is True
    assert cache["readiness"]["typed_linework"]["artifact"] == "metadata/view_linework.json"
    assert cache["readiness"]["typed_linework"]["line_count"] == 3


def test_bundle_replay_copies_linework_artifact_and_emits_cache_fields(monkeypatch, tmp_path: Path):
    bundle_dir = tmp_path / "bundle"
    source_metadata = bundle_dir / "metadata"
    source_sheets = bundle_dir / "sheets"
    source_metadata.mkdir(parents=True)
    source_sheets.mkdir()
    (source_sheets / "a-101.svg").write_text("<svg></svg>\n", encoding="utf-8")
    (source_metadata / "preflight.json").write_text(
        json.dumps({"entity_counts": {"IFCDOOR": 0, "IFCSTAIR": 0, "IFCSPACE": 0}}),
        encoding="utf-8",
    )
    linework_artifact = {
        "schema_version": 1,
        "views": [],
        "summary": {
            "view_count": 1,
            "typed_view_count": 1,
            "line_count": 2,
            "region_count": 0,
        },
    }
    (source_metadata / "view_linework.json").write_text(json.dumps(linework_artifact), encoding="utf-8")
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "job_id": "job",
                "input_sha256": "sha",
                "style_profile_id": "profile",
                "model_hash": "model",
                "pdf_path": "",
                "warnings": [],
                "sheets": [
                    {
                        "sheet_id": "A-101",
                        "title": "Floor Plan",
                        "svg_path": str(source_sheets / "a-101.svg"),
                        "page_number": 1,
                        "role": "view",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def _fake_write_pdf(destination: Path, ordered_sheets: list[Path]):
        destination.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(bundle_replay, "write_pdf_from_svg_sheets", _fake_write_pdf)

    out_dir = tmp_path / "out"
    manifest = bundle_replay.replay_bundle(bundle_dir, out_dir, profile=load_style_profile())

    copied_linework = json.loads((out_dir / "metadata" / "view_linework.json").read_text(encoding="utf-8"))
    written_manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    bundle_summary = json.loads((out_dir / "metadata" / "bundle_summary.json").read_text(encoding="utf-8"))
    assert copied_linework == linework_artifact
    assert manifest.stage_artifacts["view_linework"] == "metadata/view_linework.json"
    assert written_manifest["cache"]["readiness"]["typed_linework"]["line_count"] == 2
    assert bundle_summary["linework_summary"]["typed_view_count"] == 1


def test_bundle_replay_backfills_empty_linework_artifact_for_legacy_bundle(monkeypatch, tmp_path: Path):
    bundle_dir = tmp_path / "bundle"
    source_metadata = bundle_dir / "metadata"
    source_sheets = bundle_dir / "sheets"
    source_metadata.mkdir(parents=True)
    source_sheets.mkdir()
    (source_sheets / "a-101.svg").write_text("<svg></svg>\n", encoding="utf-8")
    (source_metadata / "preflight.json").write_text(
        json.dumps({"entity_counts": {}}),
        encoding="utf-8",
    )
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "job_id": "job",
                "input_sha256": "sha",
                "style_profile_id": "profile",
                "model_hash": "model",
                "pdf_path": "",
                "warnings": [],
                "sheets": [
                    {
                        "sheet_id": "A-101",
                        "title": "Floor Plan",
                        "svg_path": str(source_sheets / "a-101.svg"),
                        "page_number": 1,
                        "role": "view",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def _fake_write_pdf(destination: Path, ordered_sheets: list[Path]):
        destination.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(bundle_replay, "write_pdf_from_svg_sheets", _fake_write_pdf)

    out_dir = tmp_path / "out"
    manifest = bundle_replay.replay_bundle(bundle_dir, out_dir, profile=load_style_profile())

    linework = json.loads((out_dir / "metadata" / "view_linework.json").read_text(encoding="utf-8"))
    assert linework["summary"] == {
        "view_count": 0,
        "typed_view_count": 0,
        "line_count": 0,
        "region_count": 0,
    }
    assert manifest.cache["readiness"]["typed_linework"]["line_count"] == 0


def test_bundle_replay_rerenders_view_sheet_from_cached_linework(monkeypatch, tmp_path: Path):
    bundle_dir = tmp_path / "bundle"
    source_metadata = bundle_dir / "metadata"
    source_sheets = bundle_dir / "sheets"
    source_metadata.mkdir(parents=True)
    source_sheets.mkdir()
    (source_metadata / "preflight.json").write_text(
        json.dumps({"entity_counts": {"IFCDOOR": 0, "IFCSTAIR": 0, "IFCSPACE": 0}}),
        encoding="utf-8",
    )
    (source_metadata / "normalized_model.json").write_text(
        json.dumps(
            {
                "model_hash": "model",
                "project_name": "Replay Project",
                "building_name": "Replay Building",
                "schema": "IFC4",
                "source_scanner": "test",
                "storeys": [{"index": 1, "name": "Level 1", "elevation_m": 0.0}],
                "space_count": 0,
                "supported_class_counts": {"IfcWall": 1},
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    (source_metadata / "view_manifest.json").write_text(
        json.dumps(
            [
                {
                    "view_id": "floor_plan_01",
                    "sheet_id": "A-101",
                    "title": "Floor Plan - Level 1",
                    "storey_name": "Level 1",
                    "storey_elevation_m": 0.0,
                    "cut_plane_m": 1.1,
                    "view_depth_below_m": 0.2,
                    "overhead_depth_above_m": 2.3,
                    "included_classes": ["IfcWall"],
                    "view_kind": "plan",
                }
            ]
        ),
        encoding="utf-8",
    )
    (source_metadata / "view_geometry.json").write_text(
        json.dumps(
            [
                {
                    "view_id": "floor_plan_01",
                    "backend": "cached-backend",
                    "cut_candidates": {"IfcWall": 1},
                    "projection_candidates": {},
                    "source_elements": 1,
                    "path_count": 0,
                    "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 2.0, "max_y": 1.0},
                    "notes": ["cached geometry"],
                    "linework_counts": {"CUT": 1},
                    "feature_anchors": [],
                    "feature_anchor_counts": {},
                }
            ]
        ),
        encoding="utf-8",
    )
    linework_artifact = {
        "schema_version": 1,
        "views": [
            {
                "view_id": "floor_plan_01",
                "backend": "cached-backend",
                "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 2.0, "max_y": 1.0},
                "linework_counts": {"CUT": 1},
                "linework": {
                    "quantization_m": 0.001,
                    "lines": [
                        {
                            "kind": "CUT",
                            "lineweight_class": "HEAVY",
                            "points": [{"x": 0.0, "y": 0.0}, {"x": 2.0, "y": 0.0}],
                            "source_ifc_class": "IfcWall",
                            "source_element": "W1",
                        }
                    ],
                    "regions": [],
                },
            }
        ],
        "summary": {
            "view_count": 1,
            "typed_view_count": 1,
            "line_count": 1,
            "region_count": 0,
        },
    }
    (source_metadata / "view_linework.json").write_text(
        json.dumps(linework_artifact),
        encoding="utf-8",
    )
    (source_metadata / "schedule_manifest.json").write_text("[]", encoding="utf-8")
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "job_id": "old-job",
                "input_sha256": "sha",
                "style_profile_id": "old-profile",
                "model_hash": "model",
                "pdf_path": "",
                "warnings": [],
                "sheets": [],
            }
        ),
        encoding="utf-8",
    )

    def _fake_write_pdf(destination: Path, ordered_sheets: list[Path]):
        destination.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(bundle_replay, "write_pdf_from_svg_sheets", _fake_write_pdf)

    base_profile = load_style_profile()
    profile = replace(
        base_profile,
        lineweights_mm={**base_profile.lineweights_mm, "cut_primary": 0.77},
    )
    out_dir = tmp_path / "out"
    manifest = bundle_replay.replay_bundle(
        bundle_dir,
        out_dir,
        profile=profile,
        rerender_linework=True,
    )

    view_svg = out_dir / "sheets" / "a-101_level_1.svg"
    text = view_svg.read_text(encoding="utf-8")
    bundle_summary = json.loads((out_dir / "metadata" / "bundle_summary.json").read_text(encoding="utf-8"))
    written_manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "Plan linework from typed geometry kernel" in text
    assert 'stroke-width="0.77"' in text
    assert manifest.style_profile_id == profile.profile_id
    assert manifest.cache["replay"]["mode"] == "rerender_linework"
    assert written_manifest["cache"]["replay"]["rerendered_view_count"] == 1
    assert bundle_summary["replay"] == {"mode": "rerender_linework", "rerendered_view_count": 1}


def test_bundle_replay_linework_rerender_falls_back_to_copy_for_legacy_bundle(
    monkeypatch,
    tmp_path: Path,
):
    bundle_dir = tmp_path / "bundle"
    source_metadata = bundle_dir / "metadata"
    source_sheets = bundle_dir / "sheets"
    source_metadata.mkdir(parents=True)
    source_sheets.mkdir()
    (source_sheets / "a-101.svg").write_text("<svg><text>cached svg</text></svg>\n", encoding="utf-8")
    (source_metadata / "preflight.json").write_text(
        json.dumps({"entity_counts": {}}),
        encoding="utf-8",
    )
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "job_id": "job",
                "input_sha256": "sha",
                "style_profile_id": "profile",
                "model_hash": "model",
                "pdf_path": "",
                "warnings": [],
                "sheets": [
                    {
                        "sheet_id": "A-101",
                        "title": "Floor Plan",
                        "svg_path": str(source_sheets / "a-101.svg"),
                        "page_number": 1,
                        "role": "view",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def _fake_write_pdf(destination: Path, ordered_sheets: list[Path]):
        destination.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(bundle_replay, "write_pdf_from_svg_sheets", _fake_write_pdf)

    out_dir = tmp_path / "out"
    manifest = bundle_replay.replay_bundle(
        bundle_dir,
        out_dir,
        profile=load_style_profile(),
        rerender_linework=True,
    )

    text = (out_dir / "sheets" / "a-101.svg").read_text(encoding="utf-8")
    assert "cached svg" in text
    assert manifest.cache["replay"]["mode"] == "copy"
    assert any("Typed linework rerender unavailable" in warning for warning in manifest.warnings)
