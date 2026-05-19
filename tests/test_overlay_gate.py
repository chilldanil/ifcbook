from __future__ import annotations

import json
from pathlib import Path

from ifc_book_prototype import cli
from ifc_book_prototype.overlay_gate import (
    evaluate_overlay_gate_from_run_dir,
    format_overlay_gate_machine,
)


def _write_overlay_run(
    run_dir: Path,
    *,
    legend: str,
    door_arc_count: int = 0,
    feature_anchor_counts: dict | None = None,
) -> None:
    sheets_dir = run_dir / "sheets"
    metadata_dir = run_dir / "metadata"
    sheets_dir.mkdir(parents=True)
    metadata_dir.mkdir(parents=True)
    svg_path = sheets_dir / "a-101.svg"
    door_arcs = "\n".join(
        '<path data-feature="door-arc" d="M 0 0 L 1 1"/>'
        for _ in range(door_arc_count)
    )
    svg_path.write_text(
        f'<svg><text>{legend}</text>{door_arcs}</svg>\n',
        encoding="utf-8",
    )
    (metadata_dir / "view_manifest.json").write_text(
        json.dumps(
            [
                {
                    "view_id": "floor_plan_01",
                    "sheet_id": "A-101",
                    "title": "Floor Plan",
                    "storey_name": "L1",
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
                    "feature_anchor_counts": feature_anchor_counts
                    or {"IfcStair": 1, "IfcSpace": 2, "IfcDoor": 3},
                }
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "sheets": [
                    {
                        "sheet_id": "A-101",
                        "title": "Floor Plan",
                        "svg_path": str(svg_path),
                        "page_number": 1,
                        "role": "view",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_overlay_gate_passes_matching_feature_counts(tmp_path: Path):
    run_dir = tmp_path / "run"
    _write_overlay_run(
        run_dir,
        legend="Feature overlay | Stairs: 1 | Rooms: 2 | Doors: 3",
        door_arc_count=3,
    )

    result = evaluate_overlay_gate_from_run_dir(run_dir)

    assert result.passed is True
    assert result.checked_view_count == 1
    assert result.violation_count == 0
    payload = json.loads(format_overlay_gate_machine(result))
    assert payload["status"] == "PASS"


def test_overlay_gate_fails_count_mismatches(tmp_path: Path):
    run_dir = tmp_path / "run"
    _write_overlay_run(
        run_dir,
        legend="Feature overlay | Stairs: 1 | Rooms: 2 | Doors: 59",
        door_arc_count=59,
    )

    result = evaluate_overlay_gate_from_run_dir(run_dir)

    assert result.passed is False
    assert result.violation_count == 1
    assert result.violations[0].sheet_id == "A-101"
    assert result.violations[0].ifc_class == "IfcDoor"
    assert result.violations[0].expected == 3
    assert result.violations[0].rendered == 59


def test_overlay_gate_fails_door_symbol_count_mismatch(tmp_path: Path):
    run_dir = tmp_path / "run"
    _write_overlay_run(
        run_dir,
        legend="Feature overlay | Stairs: 1 | Rooms: 2 | Doors: 3",
        door_arc_count=2,
    )

    result = evaluate_overlay_gate_from_run_dir(run_dir)

    assert result.passed is False
    assert result.violations[0].source == "svg_symbol_count"
    assert result.violations[0].expected == 3
    assert result.violations[0].rendered == 2


def test_overlay_gate_skips_disabled_legend_slots(tmp_path: Path):
    run_dir = tmp_path / "run"
    _write_overlay_run(
        run_dir,
        legend="Feature overlay | Stairs: off | Rooms: 2",
        door_arc_count=0,
    )

    result = evaluate_overlay_gate_from_run_dir(run_dir)

    assert result.passed is True
    assert result.observations[0].rendered_counts == {"IfcSpace": 2}


def test_cli_overlay_gate_outputs_machine_json(tmp_path: Path, capsys):
    run_dir = tmp_path / "run"
    _write_overlay_run(
        run_dir,
        legend="Feature overlay | Stairs: 1 | Rooms: 2 | Doors: 3",
        door_arc_count=3,
    )

    exit_code = cli.main(["--overlay-gate", str(run_dir)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "OVERLAY_GATE PASS" in out
    machine_line = [line for line in out.splitlines() if line.startswith("OVERLAY_GATE_JSON=")][0]
    assert json.loads(machine_line.split("=", 1)[1])["status"] == "PASS"
