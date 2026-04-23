from __future__ import annotations

from ifc_book_prototype.domain import (
    Bounds2D,
    GeometrySummary,
    LineKind,
    LineweightClass,
    PlannedView,
    Point2D,
    TypedLine2D,
    VectorPath,
    ViewLinework,
)
from ifc_book_prototype.geometry_occt import CompositeGeometryBackend


def _make_view() -> PlannedView:
    return PlannedView(
        view_id="floor_plan_01",
        sheet_id="A-101",
        title="Floor Plan - L1",
        storey_name="L1",
        storey_elevation_m=0.0,
        cut_plane_m=1.1,
        view_depth_below_m=0.3,
        overhead_depth_above_m=2.5,
        included_classes=["IfcWall", "IfcSlab"],
    )


class _FakeOcctBackend:
    def build_view(self, view: PlannedView) -> GeometrySummary:  # noqa: ARG002
        line = TypedLine2D(
            kind=LineKind.CUT,
            lineweight_class=LineweightClass.HEAVY,
            points=[Point2D(0.0, 0.0), Point2D(1.0, 0.0)],
            source_ifc_class="IfcWall",
            source_element="W1",
        )
        return GeometrySummary(
            view_id="floor_plan_01",
            backend="occt-section",
            cut_candidates={"IfcWall": 1},
            projection_candidates={},
            source_elements=1,
            bounds=Bounds2D(min_x=0.0, min_y=0.0, max_x=1.0, max_y=1.0),
            notes=["occt note"],
            linework=ViewLinework(lines=[line], counts_by_kind={"CUT": 1}),
            linework_counts={"CUT": 1},
            fallback_events=2,
            fallback_by_class={"IfcWall": 2},
            fallback_timeout_events=1,
            fallback_exception_events=1,
            fallback_empty_events=1,
        )


class _FakeSerializerBackend:
    def build_view(self, view: PlannedView) -> GeometrySummary:  # noqa: ARG002
        return GeometrySummary(
            view_id="floor_plan_01",
            backend="ifcopenshell-svg-floorplan",
            cut_candidates={},
            projection_candidates={"IfcSlab": 3},
            source_elements=3,
            path_count=1,
            bounds=Bounds2D(min_x=-1.0, min_y=-1.0, max_x=2.0, max_y=2.0),
            paths=[
                VectorPath(
                    role="projection",
                    points=[Point2D(0.0, 0.0), Point2D(0.0, 1.0)],
                    closed=False,
                    ifc_class="IfcSlab",
                )
            ],
            notes=["serializer note"],
        )


def test_composite_backend_preserves_occt_fallback_metadata():
    backend = CompositeGeometryBackend(occt=_FakeOcctBackend(), serializer=_FakeSerializerBackend())
    summary = backend.build_view(_make_view())
    assert summary.backend == "composite-occt+serializer"
    assert summary.fallback_events == 2
    assert summary.fallback_by_class == {"IfcWall": 2}
    assert summary.fallback_timeout_events == 1
    assert summary.fallback_exception_events == 1
    assert summary.fallback_empty_events == 1
    assert summary.linework is not None
    assert summary.linework_counts == {"CUT": 1, "PROJECTED": 1}

