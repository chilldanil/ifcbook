from __future__ import annotations

from dataclasses import replace

from ifc_book_prototype.domain import (
    Bounds2D,
    FeatureAnchor2D,
    GeometrySummary,
    NormalizedModel,
    PlannedView,
    Point2D,
    StoreySummary,
    VectorPath,
)
from ifc_book_prototype.profiles import load_style_profile
from ifc_book_prototype.render_svg import render_view_svg


def _model() -> NormalizedModel:
    return NormalizedModel(
        model_hash="x" * 8,
        project_name="P",
        building_name="B",
        schema="IFC4",
        source_scanner="test",
        storeys=[StoreySummary(index=1, name="L1", elevation_m=0.0)],
        space_count=0,
        supported_class_counts={},
    )


def _view() -> PlannedView:
    return PlannedView(
        view_id="floor_plan_01",
        sheet_id="A-101",
        title="Floor Plan - L1",
        storey_name="L1",
        storey_elevation_m=0.0,
        cut_plane_m=1.1,
        view_depth_below_m=0.2,
        overhead_depth_above_m=2.3,
        included_classes=["IfcDoor", "IfcStair", "IfcSpace"],
    )


def test_svg_contains_feature_overlay_for_stairs_but_no_door_markers():
    profile = load_style_profile()
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="ifcopenshell-svg-floorplan",
        cut_candidates={"IfcDoor": 1, "IfcStair": 1},
        projection_candidates={},
        source_elements=2,
        path_count=2,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=4.0, max_y=4.0),
        paths=[
            VectorPath(
                role="projection",
                ifc_class="IfcDoor",
                points=[Point2D(0.0, 0.0), Point2D(1.0, 0.0)],
            ),
            VectorPath(
                role="projection",
                ifc_class="IfcStair",
                points=[Point2D(2.0, 2.0), Point2D(3.0, 2.0)],
            ),
        ],
    )
    svg = render_view_svg(_model(), _view(), geometry, profile)
    assert "Feature overlay | Stairs: 1 | Rooms: 0" in svg
    assert ">D</text>" not in svg
    assert ">UP</text>" in svg
    assert "Door markers" not in svg
    assert "Stair arrows" in svg
    assert "Room tags" in svg


def test_feature_overlay_is_deterministic_for_same_input():
    profile = load_style_profile()
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="ifcopenshell-svg-floorplan",
        cut_candidates={"IfcDoor": 2},
        projection_candidates={},
        source_elements=2,
        path_count=2,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=2.0, max_y=2.0),
        paths=[
            VectorPath(
                role="projection",
                ifc_class="IfcDoor",
                points=[Point2D(0.0, 0.0), Point2D(0.8, 0.0)],
            ),
            VectorPath(
                role="projection",
                ifc_class="IfcDoor",
                points=[Point2D(1.2, 1.2), Point2D(2.0, 1.2)],
            ),
        ],
    )
    svg_a = render_view_svg(_model(), _view(), geometry, profile)
    svg_b = render_view_svg(_model(), _view(), geometry, profile)
    assert svg_a == svg_b
    assert ">D</text>" not in svg_a


def test_feature_overlay_adds_room_tag_labels():
    profile = load_style_profile()
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="ifcopenshell-svg-floorplan",
        cut_candidates={"IfcSpace": 1},
        projection_candidates={},
        source_elements=1,
        path_count=1,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=8.0, max_y=8.0),
        paths=[
            VectorPath(
                role="projection",
                ifc_class="IfcSpace",
                points=[Point2D(1.0, 1.0), Point2D(7.0, 1.0), Point2D(7.0, 7.0), Point2D(1.0, 7.0), Point2D(1.0, 1.0)],
                closed=True,
            )
        ],
    )
    svg = render_view_svg(_model(), _view(), geometry, profile)
    assert "Feature overlay | Stairs: 0 | Rooms: 1" in svg
    assert ">R-001</text>" in svg


def test_profile_fixed_room_label_policy_is_respected():
    profile = load_style_profile()
    overlay = replace(
        profile.floor_plan.feature_overlay,
        room_label_mode="fixed",
        room_fixed_label="SPACE",
    )
    floor_plan = replace(profile.floor_plan, feature_overlay=overlay)
    profile = replace(profile, floor_plan=floor_plan)
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="ifcopenshell-svg-floorplan",
        cut_candidates={"IfcSpace": 1},
        projection_candidates={},
        source_elements=1,
        path_count=1,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=8.0, max_y=8.0),
        paths=[
            VectorPath(
                role="projection",
                ifc_class="IfcSpace",
                points=[Point2D(1.0, 1.0), Point2D(7.0, 1.0), Point2D(7.0, 7.0), Point2D(1.0, 7.0), Point2D(1.0, 1.0)],
                closed=True,
            )
        ],
    )
    svg = render_view_svg(_model(), _view(), geometry, profile)
    assert "Feature overlay | Stairs: 0 | Rooms: 1" in svg
    assert ">SPACE</text>" in svg


def test_semantic_feature_anchors_render_without_class_paths():
    profile = load_style_profile()
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="ifcopenshell-svg-floorplan",
        cut_candidates={},
        projection_candidates={},
        source_elements=2,
        path_count=0,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=20.0, max_y=20.0),
        paths=[],
        feature_anchors=[
            FeatureAnchor2D(
                ifc_class="IfcDoor",
                anchor=Point2D(5.0, 5.0),
                dir_x=0.0,
                dir_y=1.0,
                source_element="door-1",
            ),
            FeatureAnchor2D(
                ifc_class="IfcStair",
                anchor=Point2D(10.0, 10.0),
                dir_x=1.0,
                dir_y=0.0,
                source_element="stair-1",
            ),
        ],
    )
    svg = render_view_svg(_model(), _view(), geometry, profile)
    assert "Feature overlay | Stairs: 1 | Rooms: 0" in svg
    assert ">D</text>" not in svg
    assert ">UP</text>" in svg


def test_semantic_door_anchors_suppress_geometry_path_door_duplicates():
    profile = load_style_profile()
    overlay = replace(profile.floor_plan.feature_overlay, doors_enabled=True)
    profile = replace(profile, floor_plan=replace(profile.floor_plan, feature_overlay=overlay))
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="ifcopenshell-svg-floorplan",
        cut_candidates={"IfcDoor": 3},
        projection_candidates={},
        source_elements=3,
        path_count=2,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=12.0, max_y=8.0),
        paths=[
            VectorPath(
                role="projection",
                ifc_class="IfcDoor",
                points=[Point2D(1.0, 1.0), Point2D(2.0, 1.0)],
            ),
            VectorPath(
                role="projection",
                ifc_class="IfcDoor",
                points=[Point2D(9.0, 6.0), Point2D(10.0, 6.0)],
            ),
        ],
        feature_anchors=[
            FeatureAnchor2D(
                ifc_class="IfcDoor",
                anchor=Point2D(5.0, 4.0),
                dir_x=1.0,
                dir_y=0.0,
                source_element="door-1",
            )
        ],
        feature_anchor_counts={"IfcDoor": 1},
    )

    svg = render_view_svg(_model(), _view(), geometry, profile)

    assert "Feature overlay | Stairs: 0 | Rooms: 0 | Doors: 1" in svg
    assert svg.count('data-feature="door-arc"') == 1


def test_room_label_mode_ifc_name_uses_semantic_label():
    profile = load_style_profile()
    overlay = replace(profile.floor_plan.feature_overlay, room_label_mode="ifc_name")
    floor_plan = replace(profile.floor_plan, feature_overlay=overlay)
    profile = replace(profile, floor_plan=floor_plan)
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="ifcopenshell-svg-floorplan",
        cut_candidates={},
        projection_candidates={},
        source_elements=1,
        path_count=0,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=20.0, max_y=20.0),
        paths=[],
        feature_anchors=[
            FeatureAnchor2D(
                ifc_class="IfcSpace",
                anchor=Point2D(8.0, 8.0),
                dir_x=1.0,
                dir_y=0.0,
                source_element="space-1",
                label="Living Room",
            )
        ],
    )
    svg = render_view_svg(_model(), _view(), geometry, profile)
    assert "Feature overlay | Stairs: 0 | Rooms: 1" in svg
    assert ">Living Room</text>" in svg


def test_room_label_mode_ifc_name_prefers_structured_display_label():
    profile = load_style_profile()
    overlay = replace(profile.floor_plan.feature_overlay, room_label_mode="ifc_name")
    floor_plan = replace(profile.floor_plan, feature_overlay=overlay)
    profile = replace(profile, floor_plan=floor_plan)
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="ifcopenshell-svg-floorplan",
        cut_candidates={},
        projection_candidates={},
        source_elements=1,
        path_count=0,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=20.0, max_y=20.0),
        paths=[],
        feature_anchors=[
            FeatureAnchor2D(
                ifc_class="IfcSpace",
                anchor=Point2D(8.0, 8.0),
                dir_x=1.0,
                dir_y=0.0,
                source_element="space-1",
                display_label="A-12 Lobby",
                label="Legacy Room",
            )
        ],
    )
    svg = render_view_svg(_model(), _view(), geometry, profile)
    assert ">A-12 Lobby</text>" in svg
    assert ">Legacy Room</text>" not in svg
