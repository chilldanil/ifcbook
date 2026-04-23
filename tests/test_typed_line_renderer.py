"""Typed-line renderer correctness."""
from __future__ import annotations

from ifc_book_prototype.domain import (
    Bounds2D,
    GeometrySummary,
    LineKind,
    LineweightClass,
    NormalizedModel,
    PlannedView,
    Point2D,
    StoreySummary,
    TypedLine2D,
    VectorPath,
    ViewLinework,
)
from ifc_book_prototype.profiles import load_style_profile
from ifc_book_prototype.render_svg import (
    _lineweight_for_typed_line,
    render_view_svg,
)


def _make_view() -> PlannedView:
    return PlannedView(
        view_id="floor_plan_01",
        sheet_id="A-101",
        title="Floor Plan - Test",
        storey_name="Test",
        storey_elevation_m=0.0,
        cut_plane_m=1.1,
        view_depth_below_m=0.2,
        overhead_depth_above_m=2.3,
        included_classes=["IfcWall"],
    )


def _make_model() -> NormalizedModel:
    return NormalizedModel(
        model_hash="x" * 8,
        project_name="P",
        building_name="B",
        schema="IFC4",
        source_scanner="test",
        storeys=[StoreySummary(index=1, name="Test", elevation_m=0.0)],
        space_count=0,
        supported_class_counts={},
    )


def test_lineweight_heavy_maps_to_cut_primary():
    profile = load_style_profile()
    line = TypedLine2D(
        kind=LineKind.CUT,
        lineweight_class=LineweightClass.HEAVY,
        points=[Point2D(0.0, 0.0), Point2D(1.0, 0.0)],
    )
    assert _lineweight_for_typed_line(line, profile) == profile.lineweights_mm["cut_primary"]


def test_lineweight_class_table_covers_all_classes():
    profile = load_style_profile()
    expected = {
        LineweightClass.HEAVY: profile.lineweights_mm["cut_primary"],
        LineweightClass.MEDIUM: profile.lineweights_mm["cut_secondary"],
        LineweightClass.LIGHT: profile.lineweights_mm["projected"],
        LineweightClass.FINE: profile.lineweights_mm["overhead"],
    }
    for klass, weight in expected.items():
        line = TypedLine2D(
            kind=LineKind.CUT,
            lineweight_class=klass,
            points=[Point2D(0.0, 0.0), Point2D(1.0, 0.0)],
        )
        assert _lineweight_for_typed_line(line, profile) == weight


def test_typed_renderer_takes_precedence_over_legacy_paths():
    profile = load_style_profile()
    typed_line = TypedLine2D(
        kind=LineKind.CUT,
        lineweight_class=LineweightClass.HEAVY,
        points=[Point2D(0.0, 0.0), Point2D(2.0, 0.0), Point2D(2.0, 2.0)],
        closed=True,
        source_ifc_class="IfcWall",
        source_element="0xLEGENDARY_WALL",
    )
    linework = ViewLinework(lines=[typed_line], counts_by_kind={"CUT": 1})
    legacy_path = VectorPath(
        role="cut",
        points=[Point2D(10.0, 10.0), Point2D(11.0, 10.0)],
        ifc_class="IfcWall",
    )
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="test",
        cut_candidates={"IfcWall": 1},
        projection_candidates={},
        source_elements=1,
        path_count=1,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=2.0, max_y=2.0),
        paths=[legacy_path],
        linework=linework,
        linework_counts={"CUT": 1},
    )
    svg = render_view_svg(_make_model(), _make_view(), geometry, profile)
    # Typed rendering signature
    assert "typed geometry kernel" in svg
    assert "#111827" in svg
    # Legacy serializer banner must NOT appear when typed path is taken
    assert "IfcOpenShell floorplan serializer" not in svg


def test_typed_renderer_omits_when_linework_absent():
    profile = load_style_profile()
    legacy_path = VectorPath(
        role="cut",
        points=[Point2D(0.0, 0.0), Point2D(1.0, 0.0)],
        ifc_class="IfcWall",
    )
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="test",
        cut_candidates={"IfcWall": 1},
        projection_candidates={},
        source_elements=1,
        path_count=1,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=1.0, max_y=1.0),
        paths=[legacy_path],
        linework=None,
    )
    svg = render_view_svg(_make_model(), _make_view(), geometry, profile)
    assert "IfcOpenShell floorplan serializer" in svg
    assert "typed geometry kernel" not in svg
