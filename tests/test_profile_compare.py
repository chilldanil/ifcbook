from __future__ import annotations

import json
from pathlib import Path

from ifc_book_prototype import cli
from ifc_book_prototype.profile_compare import (
    compare_profile_rerenders,
    format_profile_comparison_human,
    parse_profile_list,
    write_profile_comparison_report,
)


def _write_minimal_linework_bundle(bundle_dir: Path) -> None:
    metadata_dir = bundle_dir / "metadata"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "preflight.json").write_text(
        json.dumps({"entity_counts": {"IFCDOOR": 0, "IFCSTAIR": 0, "IFCSPACE": 0}}),
        encoding="utf-8",
    )
    (metadata_dir / "normalized_model.json").write_text(
        json.dumps(
            {
                "model_hash": "model",
                "project_name": "Compare Project",
                "building_name": "Compare Building",
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
    (metadata_dir / "view_manifest.json").write_text(
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
    (metadata_dir / "view_geometry.json").write_text(
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
                    "notes": [],
                    "linework_counts": {"CUT": 1},
                    "feature_anchors": [],
                    "feature_anchor_counts": {},
                }
            ]
        ),
        encoding="utf-8",
    )
    (metadata_dir / "view_linework.json").write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )
    (metadata_dir / "schedule_manifest.json").write_text("[]", encoding="utf-8")
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


def test_parse_profile_list_defaults_and_accepts_csv():
    assert parse_profile_list(None) == ("presentation", "permit_set", "coordination")
    assert parse_profile_list("presentation, permit_set") == ("presentation", "permit_set")


def test_compare_profile_rerenders_reports_same_geometry_and_different_outputs(tmp_path: Path):
    bundle_dir = tmp_path / "bundle"
    _write_minimal_linework_bundle(bundle_dir)

    report = compare_profile_rerenders(
        bundle_dir=bundle_dir,
        output_root=tmp_path / "compare",
        profiles=("presentation", "permit_set"),
        sheet_id="A-101",
    )
    json_path, markdown_path = write_profile_comparison_report(report)

    assert report.geometry_hashes_match is True
    assert report.sheet_hashes_differ is True
    assert report.pdf_hashes_differ is True
    assert report.compared_sheet_id == "A-101"
    assert [item.profile for item in report.items] == ["presentation", "permit_set"]
    assert {item.replay_mode for item in report.items} == {"rerender_linework"}
    assert json.loads(json_path.read_text(encoding="utf-8"))["checks"]["geometry_hashes_match"] is True
    assert "presentation" in markdown_path.read_text(encoding="utf-8")
    assert "geometry_hashes_match=true" in format_profile_comparison_human(report)


def test_cli_compare_profiles_writes_reports(tmp_path: Path, capsys):
    bundle_dir = tmp_path / "bundle"
    out_dir = tmp_path / "compare"
    _write_minimal_linework_bundle(bundle_dir)

    exit_code = cli.main(
        [
            "--compare-profiles",
            str(bundle_dir),
            "--profiles",
            "presentation,permit_set",
            "--compare-sheet",
            "A-101",
            "--out",
            str(out_dir),
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "PROFILE_COMPARISON" in out
    assert "geometry_hashes_match=true" in out
    assert (out_dir / "profile_comparison.json").exists()
    assert (out_dir / "profile_comparison.md").exists()
