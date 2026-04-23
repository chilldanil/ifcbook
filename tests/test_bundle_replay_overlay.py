from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ifc_book_prototype.profiles import load_style_profile
from ifc_book_prototype.bundle_replay import _inject_replay_feature_overlay


def test_replay_overlay_injected_when_counts_present(tmp_path: Path):
    svg = tmp_path / "sheet.svg"
    svg.write_text('<svg width="100" height="100"></svg>\n', encoding="utf-8")
    _inject_replay_feature_overlay(svg, door_count=5, stair_count=2, room_count=3)
    text = svg.read_text(encoding="utf-8")
    assert "Replay feature overlay | Doors: 5 | Stairs: 2 | Rooms: 3" in text
    assert ">D</text>" in text
    assert ">UP</text>" in text
    assert ">R</text>" in text
    assert "x 5" in text
    assert "x 2" in text
    assert "x 3" in text


def test_replay_overlay_not_injected_when_counts_zero(tmp_path: Path):
    svg = tmp_path / "sheet.svg"
    original = '<svg width="100" height="100"></svg>\n'
    svg.write_text(original, encoding="utf-8")
    _inject_replay_feature_overlay(svg, door_count=0, stair_count=0, room_count=0)
    assert svg.read_text(encoding="utf-8") == original


def test_replay_overlay_respects_profile_feature_toggles(tmp_path: Path):
    svg = tmp_path / "sheet.svg"
    svg.write_text('<svg width="100" height="100"></svg>\n', encoding="utf-8")
    profile = load_style_profile()
    overlay = replace(profile.floor_plan.feature_overlay, doors_enabled=False, rooms_enabled=False)
    _inject_replay_feature_overlay(svg, door_count=5, stair_count=2, room_count=3, overlay_style=overlay)
    text = svg.read_text(encoding="utf-8")
    assert "Replay feature overlay | Doors: off | Stairs: 2 | Rooms: off" in text
    assert ">D</text>" not in text
    assert ">UP</text>" in text


def test_replay_overlay_renders_symbols_from_serialized_view_anchors(tmp_path: Path):
    svg = tmp_path / "sheet.svg"
    svg.write_text('<svg width="100" height="100"></svg>\n', encoding="utf-8")
    _inject_replay_feature_overlay(
        svg,
        door_count=1,
        stair_count=1,
        room_count=1,
        view_overlay={
            "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 10.0, "max_y": 10.0},
            "feature_anchors": [
                {"ifc_class": "IfcDoor", "anchor": {"x": 1.0, "y": 1.0}, "dir_x": 1.0, "dir_y": 0.0, "source_element": "d-1"},
                {"ifc_class": "IfcStair", "anchor": {"x": 2.0, "y": 2.0}, "dir_x": 0.0, "dir_y": 1.0, "source_element": "s-1"},
                {"ifc_class": "IfcSpace", "anchor": {"x": 3.0, "y": 3.0}, "label": "Room A", "source_element": "r-1"},
            ],
        },
    )
    text = svg.read_text(encoding="utf-8")
    assert "Replay feature overlay | Doors: 1 | Stairs: 1 | Rooms: 1" in text
    assert ">D</text>" in text
    assert ">UP</text>" in text
    assert ">Room A</text>" in text


def test_replay_overlay_skips_duplicate_symbols_when_sheet_already_has_feature_overlay(tmp_path: Path):
    svg = tmp_path / "sheet.svg"
    svg.write_text(
        '<svg width="100" height="100"><text>Feature overlay | Doors: 1 | Stairs: 1 | Rooms: 0</text></svg>\n',
        encoding="utf-8",
    )
    _inject_replay_feature_overlay(
        svg,
        door_count=1,
        stair_count=1,
        room_count=0,
        view_overlay={
            "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 10.0, "max_y": 10.0},
            "feature_anchors": [
                {"ifc_class": "IfcDoor", "anchor": {"x": 1.0, "y": 1.0}, "dir_x": 1.0, "dir_y": 0.0, "source_element": "d-1"},
            ],
        },
    )
    text = svg.read_text(encoding="utf-8")
    assert "Replay feature overlay | Doors: 1 | Stairs: 1 | Rooms: 0" in text
    # No replay-placed per-anchor symbols should be injected (they use 1.8 text).
    assert 'font-size="1.8"' not in text
