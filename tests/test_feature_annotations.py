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


def test_svg_contains_feature_overlay_for_doors_and_stairs():
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
    assert "Feature overlay | Doors: 1 | Stairs: 1 | Rooms: 0" in svg
    assert ">D</text>" in svg
    assert ">UP</text>" in svg
    assert "Door markers" in svg
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


def test_feature_overlay_applies_collision_avoidance_with_leader():
    profile = load_style_profile()
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="ifcopenshell-svg-floorplan",
        cut_candidates={"IfcDoor": 2},
        projection_candidates={},
        source_elements=2,
        path_count=2,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=200.0, max_y=200.0),
        paths=[
            VectorPath(
                role="projection",
                ifc_class="IfcDoor",
                points=[Point2D(10.0, 100.0), Point2D(10.8, 100.0)],
            ),
            VectorPath(
                role="projection",
                ifc_class="IfcDoor",
                points=[Point2D(10.7, 100.0), Point2D(11.5, 100.0)],
            ),
        ],
    )
    svg = render_view_svg(_model(), _view(), geometry, profile)
    assert "Feature overlay | Doors: 2 | Stairs: 0 | Rooms: 0" in svg
    assert 'data-feature="leader"' in svg


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
    assert "Feature overlay | Doors: 0 | Stairs: 0 | Rooms: 1" in svg
    assert ">R-001</text>" in svg


def test_profile_can_disable_doors_in_overlay():
    profile = load_style_profile()
    overlay = replace(profile.floor_plan.feature_overlay, doors_enabled=False)
    floor_plan = replace(profile.floor_plan, feature_overlay=overlay)
    profile = replace(profile, floor_plan=floor_plan)
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="ifcopenshell-svg-floorplan",
        cut_candidates={"IfcDoor": 1},
        projection_candidates={},
        source_elements=1,
        path_count=1,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=2.0, max_y=2.0),
        paths=[
            VectorPath(
                role="projection",
                ifc_class="IfcDoor",
                points=[Point2D(0.0, 0.0), Point2D(1.0, 0.0)],
            )
        ],
    )
    svg = render_view_svg(_model(), _view(), geometry, profile)
    assert "Feature overlay | Doors: off | Stairs: 0 | Rooms: 0" in svg
    assert ">D</text>" not in svg


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
    assert "Feature overlay | Doors: 0 | Stairs: 0 | Rooms: 1" in svg
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
    assert "Feature overlay | Doors: 1 | Stairs: 1 | Rooms: 0" in svg
    assert ">D</text>" in svg
    assert ">UP</text>" in svg


def test_door_semantic_left_right_hints_produce_different_deterministic_svg():
    profile = load_style_profile()
    left_geometry = GeometrySummary(
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
                ifc_class="IfcDoor",
                anchor=Point2D(5.0, 5.0),
                dir_x=1.0,
                dir_y=0.0,
                source_element="door-left",
                label="door_swing:left",
            )
        ],
    )
    right_geometry = replace(
        left_geometry,
        feature_anchors=[
            replace(left_geometry.feature_anchors[0], source_element="door-right", label="door_swing:right")
        ],
    )

    left_svg_a = render_view_svg(_model(), _view(), left_geometry, profile)
    left_svg_b = render_view_svg(_model(), _view(), left_geometry, profile)
    right_svg_a = render_view_svg(_model(), _view(), right_geometry, profile)
    right_svg_b = render_view_svg(_model(), _view(), right_geometry, profile)

    assert left_svg_a == left_svg_b
    assert right_svg_a == right_svg_b
    assert left_svg_a != right_svg_a
    assert ">D</text>" in left_svg_a
    assert ">D</text>" in right_svg_a


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
    assert "Feature overlay | Doors: 0 | Stairs: 0 | Rooms: 1" in svg
    assert ">Living Room</text>" in svg
