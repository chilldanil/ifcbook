from __future__ import annotations

from pathlib import Path

from ifc_book_prototype.domain import (
    Bounds2D,
    FeatureAnchor2D,
    GeometrySummary,
    LineKind,
    LineweightClass,
    NormalizedModel,
    PlannedView,
    Point2D,
    StoreySummary,
    TypedLine2D,
    ViewLinework,
)
from ifc_book_prototype.profiles import PACKAGE_ROOT, load_style_profile
from ifc_book_prototype.render_svg import render_view_svg


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "visual"


def _model() -> NormalizedModel:
    return NormalizedModel(
        model_hash="v" * 8,
        project_name="Visual Fixture",
        building_name="Fixture Building",
        schema="IFC4",
        source_scanner="tests",
        storeys=[StoreySummary(index=1, name="L1", elevation_m=0.0)],
        space_count=1,
        supported_class_counts={"IfcWall": 1, "IfcDoor": 1, "IfcSpace": 1},
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
        included_classes=["IfcWall", "IfcDoor", "IfcSpace"],
    )


def test_phase3c_owned_projection_hidden_visual_fixture_matches():
    profile_path = PACKAGE_ROOT / "profiles" / "din_iso_arch_floor_plan_v3_phase3c_owned_projection_hidden.json"
    profile = load_style_profile(str(profile_path))
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="composite-occt+serializer",
        cut_candidates={"IfcWall": 1},
        projection_candidates={"IfcWall": 1},
        source_elements=3,
        path_count=0,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=8.0, max_y=6.0),
        linework=ViewLinework(
            lines=[
                TypedLine2D(
                    kind=LineKind.CUT,
                    lineweight_class=LineweightClass.HEAVY,
                    points=[Point2D(0.0, 0.0), Point2D(8.0, 0.0)],
                    source_ifc_class="IfcWall",
                    source_element="W1",
                ),
                TypedLine2D(
                    kind=LineKind.PROJECTED,
                    lineweight_class=LineweightClass.LIGHT,
                    points=[Point2D(0.0, 2.0), Point2D(8.0, 2.0)],
                    source_ifc_class="IfcWall",
                    source_element="W1",
                ),
                TypedLine2D(
                    kind=LineKind.HIDDEN,
                    lineweight_class=LineweightClass.FINE,
                    points=[Point2D(0.5, 3.5), Point2D(7.5, 3.5)],
                    source_ifc_class="IfcWall",
                    source_element="W2",
                ),
            ],
            counts_by_kind={"CUT": 1, "PROJECTED": 1, "HIDDEN": 1},
        ),
        linework_counts={"CUT": 1, "PROJECTED": 1, "HIDDEN": 1},
        feature_anchors=[
            FeatureAnchor2D(
                ifc_class="IfcDoor",
                anchor=Point2D(1.0, 1.0),
                dir_x=1.0,
                dir_y=0.0,
                source_element="door-1",
                label="door_swing:left",
            ),
            FeatureAnchor2D(
                ifc_class="IfcSpace",
                anchor=Point2D(5.0, 4.0),
                dir_x=1.0,
                dir_y=0.0,
                source_element="space-1",
                label="A-12 Lobby",
            ),
        ],
        feature_anchor_counts={"IfcDoor": 1, "IfcSpace": 1},
        notes=[
            "Projection source: owned (serializer projection suppressed).",
            "Owned projection output: 1 projected line(s), 1 hidden line(s).",
        ],
    )

    actual_svg = render_view_svg(_model(), _view(), geometry, profile)
    expected_svg = (FIXTURE_DIR / "phase3c_owned_projection_hidden.svg").read_text(encoding="utf-8")
    assert actual_svg == expected_svg
