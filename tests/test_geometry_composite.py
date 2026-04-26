from __future__ import annotations

from dataclasses import replace

from ifc_book_prototype import geometry_projection
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
from ifc_book_prototype.geometry_occt import CompositeGeometryBackend, _element_matches_any_ifc_class
from ifc_book_prototype.profiles import load_style_profile


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


class _FakeOcctBackendWithProfile(_FakeOcctBackend):
    def __init__(self, profile) -> None:
        self.profile = profile
        self._ifc_geom = object()
        self._storey_elevations = {"L1": 0.0}
        self._elements_by_storey = {"L1": [object()]}


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
    assert summary.projection_candidates == {"IfcSlab": 3}
    assert "Projection source: serializer." in summary.notes


def test_composite_backend_uses_owned_projection_when_toggle_enabled(monkeypatch):
    profile = load_style_profile(None)
    profile = replace(profile, floor_plan=replace(profile.floor_plan, own_projection=True))
    backend = CompositeGeometryBackend(
        occt=_FakeOcctBackendWithProfile(profile),
        serializer=_FakeSerializerBackend(),
    )

    owned_projected = [
        TypedLine2D(
            kind=LineKind.PROJECTED,
            lineweight_class=LineweightClass.LIGHT,
            points=[Point2D(2.0, 2.0), Point2D(3.0, 2.0)],
            source_ifc_class="IfcColumn",
        ),
        TypedLine2D(
            kind=LineKind.PROJECTED,
            lineweight_class=LineweightClass.LIGHT,
            points=[Point2D(4.0, 4.0), Point2D(5.0, 4.0)],
            source_ifc_class="IfcWall",
        ),
    ]
    owned_hidden = [
        TypedLine2D(
            kind=LineKind.HIDDEN,
            lineweight_class=LineweightClass.LIGHT,
            points=[Point2D(9.0, 9.0), Point2D(10.0, 10.0)],
            source_ifc_class="IfcSlab",
        )
    ]
    merge_call: dict[str, object] = {}
    real_merge = geometry_projection.merge_owned_lines_into

    monkeypatch.setattr(
        geometry_projection,
        "extract_owned_projection_lines",
        lambda **_: list(owned_projected),
    )
    monkeypatch.setattr(
        geometry_projection,
        "extract_owned_hidden_lines",
        lambda **_: list(owned_hidden),
    )

    def _spy_merge(base_lines, owned_projection, owned_hidden, *, suppress_serializer_projection):
        merge_call["base_line_count"] = len(base_lines)
        merge_call["suppress_serializer_projection"] = suppress_serializer_projection
        return real_merge(
            base_lines=base_lines,
            owned_projection=owned_projection,
            owned_hidden=owned_hidden,
            suppress_serializer_projection=suppress_serializer_projection,
        )

    monkeypatch.setattr(geometry_projection, "merge_owned_lines_into", _spy_merge)

    summary = backend.build_view(_make_view())

    assert merge_call["base_line_count"] == 2  # 1 OCCT cut + 1 serializer projected
    assert merge_call["suppress_serializer_projection"] is True
    assert summary.projection_candidates == {"IfcColumn": 1, "IfcWall": 1}
    assert "Projection source: owned (serializer projection suppressed)." in summary.notes
    assert "Owned projection output: 2 projected line(s), 1 hidden line(s)." in summary.notes
    assert summary.linework_counts == {"CUT": 1, "HIDDEN": 1, "PROJECTED": 2}
    assert summary.linework is not None
    projected_classes = sorted(
        line.source_ifc_class
        for line in summary.linework.lines
        if line.kind is LineKind.PROJECTED and line.source_ifc_class
    )
    assert projected_classes == ["IfcColumn", "IfcWall"]


def test_composite_backend_keeps_serializer_projection_when_owned_disabled(monkeypatch):
    profile = load_style_profile(None)
    backend = CompositeGeometryBackend(
        occt=_FakeOcctBackendWithProfile(profile),
        serializer=_FakeSerializerBackend(),
    )
    merge_call: dict[str, object] = {}
    real_merge = geometry_projection.merge_owned_lines_into

    monkeypatch.setattr(
        geometry_projection,
        "extract_owned_projection_lines",
        lambda **_: [],
    )
    monkeypatch.setattr(
        geometry_projection,
        "extract_owned_hidden_lines",
        lambda **_: [],
    )

    def _spy_merge(base_lines, owned_projection, owned_hidden, *, suppress_serializer_projection):
        merge_call["base_line_count"] = len(base_lines)
        merge_call["suppress_serializer_projection"] = suppress_serializer_projection
        return real_merge(
            base_lines=base_lines,
            owned_projection=owned_projection,
            owned_hidden=owned_hidden,
            suppress_serializer_projection=suppress_serializer_projection,
        )

    monkeypatch.setattr(geometry_projection, "merge_owned_lines_into", _spy_merge)

    summary = backend.build_view(_make_view())

    assert merge_call["base_line_count"] == 2  # 1 OCCT cut + 1 serializer projected
    assert merge_call["suppress_serializer_projection"] is False
    assert summary.projection_candidates == {"IfcSlab": 3}
    assert summary.linework_counts == {"CUT": 1, "PROJECTED": 1}
    assert "Projection source: serializer." in summary.notes


def test_cut_class_matching_accepts_ifc_subtypes() -> None:
    class _SubtypeElement:
        def is_a(self, class_name=None):
            if class_name is None:
                return "IfcWallStandardCase"
            return class_name == "IfcWall"

    assert _element_matches_any_ifc_class(_SubtypeElement(), ["IfcWall"]) is True
