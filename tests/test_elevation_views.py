"""Elevation view planning + renderer contract tests.

These tests verify the non-OCCT path: view planner emits 4 elevations, the
elevation backend returns an honest empty summary without ``pythonocc-core``,
the renderer produces a deterministic SVG for the empty case, and the
determinism gate in ``test_determinism.py`` keeps byte-identity.
"""
from __future__ import annotations

from pathlib import Path

from ifc_book_prototype.domain import (
    ELEVATION_VIEW_KINDS,
    NormalizedModel,
    PlannedView,
    StoreySummary,
    VIEW_KIND_ELEVATION_EAST,
    VIEW_KIND_ELEVATION_NORTH,
    VIEW_KIND_ELEVATION_SOUTH,
    VIEW_KIND_ELEVATION_WEST,
    VIEW_KIND_PLAN,
)
from ifc_book_prototype.elevation_backend import (
    ElevationBackend,
    axis_projector_for_view_kind,
    is_elevation_view,
)
from ifc_book_prototype.pipeline import PrototypePipeline
from ifc_book_prototype.profiles import load_style_profile


def _make_model(storeys=(("L1", 0.0),)) -> NormalizedModel:
    return NormalizedModel(
        model_hash="deadbeef",
        project_name="Test",
        building_name="Test",
        schema="IFC4",
        source_scanner="test",
        storeys=[
            StoreySummary(index=i + 1, name=name, elevation_m=elev)
            for i, (name, elev) in enumerate(storeys)
        ],
        space_count=0,
        supported_class_counts={},
    )


def test_view_kinds_contain_four_elevations() -> None:
    assert set(ELEVATION_VIEW_KINDS) == {
        VIEW_KIND_ELEVATION_NORTH,
        VIEW_KIND_ELEVATION_SOUTH,
        VIEW_KIND_ELEVATION_EAST,
        VIEW_KIND_ELEVATION_WEST,
    }


def test_planner_emits_four_elevations_after_storey_plans() -> None:
    profile = load_style_profile(None)
    pipeline = PrototypePipeline(profile)
    model = _make_model(storeys=(("L1", 0.0), ("L2", 3.0)))
    views = pipeline._plan_views(model)  # type: ignore[attr-defined]
    plan_views = [v for v in views if v.view_kind == VIEW_KIND_PLAN]
    elevation_views = [v for v in views if v.view_kind in ELEVATION_VIEW_KINDS]
    assert len(plan_views) == 2
    assert len(elevation_views) == 4
    # Sheet IDs in stable order.
    assert [v.sheet_id for v in elevation_views] == ["A-201", "A-202", "A-203", "A-204"]
    assert [v.view_kind for v in elevation_views] == [
        VIEW_KIND_ELEVATION_NORTH,
        VIEW_KIND_ELEVATION_EAST,
        VIEW_KIND_ELEVATION_SOUTH,
        VIEW_KIND_ELEVATION_WEST,
    ]


def test_planner_emits_elevations_even_with_synthetic_single_storey() -> None:
    profile = load_style_profile(None)
    pipeline = PrototypePipeline(profile)
    model = _make_model()
    views = pipeline._plan_views(model)  # type: ignore[attr-defined]
    assert sum(1 for v in views if v.view_kind in ELEVATION_VIEW_KINDS) == 4


def test_axis_projector_mirrors_opposite_elevations() -> None:
    """N and S mirror on the horizontal axis; so do E and W."""
    n = axis_projector_for_view_kind(VIEW_KIND_ELEVATION_NORTH)
    s = axis_projector_for_view_kind(VIEW_KIND_ELEVATION_SOUTH)
    e = axis_projector_for_view_kind(VIEW_KIND_ELEVATION_EAST)
    w = axis_projector_for_view_kind(VIEW_KIND_ELEVATION_WEST)
    assert n(3.0, 5.0, 7.0) == (3.0, 7.0)
    assert s(3.0, 5.0, 7.0) == (-3.0, 7.0)
    assert e(3.0, 5.0, 7.0) == (-5.0, 7.0)
    assert w(3.0, 5.0, 7.0) == (5.0, 7.0)


def test_elevation_backend_empty_without_occt(tmp_path: Path) -> None:
    """Without OCCT, ElevationBackend must return a deterministic empty summary.

    This is the entire local-env contract: the pipeline must still produce
    elevation sheets byte-identically, even when no real geometry can be
    extracted.
    """
    profile = load_style_profile(None)
    backend = ElevationBackend(ifc_path=tmp_path / "fake.ifc", profile=profile)
    view = PlannedView(
        view_id="elev_n",
        sheet_id="A-201",
        title="North Elevation",
        storey_name="",
        storey_elevation_m=None,
        cut_plane_m=0.0,
        view_depth_below_m=0.0,
        overhead_depth_above_m=0.0,
        included_classes=[],
        view_kind=VIEW_KIND_ELEVATION_NORTH,
    )
    summary = backend.build_view(view)
    assert summary.backend == "occt-elevation-edges"
    assert summary.bounds is None
    assert summary.source_elements == 0
    assert summary.linework is None
    assert summary.notes  # non-empty note explaining why empty


def test_is_elevation_view_helper() -> None:
    plan = PlannedView(
        view_id="p",
        sheet_id="A-101",
        title="Plan",
        storey_name="L1",
        storey_elevation_m=0.0,
        cut_plane_m=1.1,
        view_depth_below_m=0.2,
        overhead_depth_above_m=2.3,
        included_classes=[],
        view_kind=VIEW_KIND_PLAN,
    )
    assert not is_elevation_view(plan)
    for kind in ELEVATION_VIEW_KINDS:
        e = PlannedView(
            view_id="e",
            sheet_id="A-201",
            title=kind,
            storey_name="",
            storey_elevation_m=None,
            cut_plane_m=0.0,
            view_depth_below_m=0.0,
            overhead_depth_above_m=0.0,
            included_classes=[],
            view_kind=kind,
        )
        assert is_elevation_view(e)
