from __future__ import annotations

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
