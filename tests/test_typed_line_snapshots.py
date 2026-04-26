"""Snapshot-style typed renderer regression checks."""
from __future__ import annotations

import hashlib

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
    ViewLinework,
)
from ifc_book_prototype.profiles import load_style_profile
from ifc_book_prototype.render_svg import render_view_svg


def _make_view() -> PlannedView:
    return PlannedView(
        view_id="floor_plan_01",
        sheet_id="A-101",
        title="Floor Plan - L1",
        storey_name="L1",
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
        storeys=[StoreySummary(index=1, name="L1", elevation_m=0.0)],
        space_count=0,
        supported_class_counts={},
    )


def test_typed_plan_svg_snapshot_hash_is_stable():
    profile = load_style_profile()
    # Intentionally unsorted input; renderer must apply deterministic ordering.
    lines = [
        TypedLine2D(
            kind=LineKind.HIDDEN,
            lineweight_class=LineweightClass.FINE,
            points=[Point2D(0.0, 2.0), Point2D(4.0, 2.0)],
            source_ifc_class="IfcWall",
            source_element="W1",
        ),
        TypedLine2D(
            kind=LineKind.CUT,
            lineweight_class=LineweightClass.HEAVY,
            points=[Point2D(0.0, 0.0), Point2D(4.0, 0.0)],
            source_ifc_class="IfcWall",
            source_element="W1",
        ),
        TypedLine2D(
            kind=LineKind.PROJECTED,
            lineweight_class=LineweightClass.LIGHT,
            points=[Point2D(0.0, 1.0), Point2D(4.0, 1.0)],
            source_ifc_class="IfcWall",
            source_element="W1",
        ),
    ]
    geometry = GeometrySummary(
        view_id="floor_plan_01",
        backend="test",
        cut_candidates={"IfcWall": 1},
        projection_candidates={"IfcWall": 1},
        source_elements=1,
        path_count=0,
        bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=4.0, max_y=3.0),
        linework=ViewLinework(lines=lines, counts_by_kind={"CUT": 1, "PROJECTED": 1, "HIDDEN": 1}),
        linework_counts={"CUT": 1, "PROJECTED": 1, "HIDDEN": 1},
    )
    svg = render_view_svg(_make_model(), _make_view(), geometry, profile)
    assert hashlib.sha256(svg.encode("utf-8")).hexdigest() == (
        "9919cd68d48bcc6a1373777edebf2f2686db432ddd80f2a40028d2f4566dbe64"
    )
    assert 'stroke-dasharray="1.3 1.3"' in svg
    assert "typed geometry kernel" in svg

