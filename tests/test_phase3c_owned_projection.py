"""Phase 3C: owned projection/hidden scaffolding.

These tests verify the contract surface only. Actual owned projection/hidden
line generation lands later; the scaffolding here just has to be honest about
its gates and not break the default path.
"""
from __future__ import annotations

from dataclasses import replace

from ifc_book_prototype import geometry_projection
from ifc_book_prototype.domain import LineKind, LineweightClass, Point2D, TypedLine2D
from ifc_book_prototype.profiles import load_style_profile


def test_default_profile_owned_projection_disabled() -> None:
    """Default profile keeps serializer projection — back-compat."""
    profile = load_style_profile(None)
    assert profile.floor_plan.own_projection is False
    assert profile.floor_plan.own_hidden is False
    assert geometry_projection.owned_projection_enabled(profile) is False
    assert geometry_projection.owned_hidden_enabled(profile) is False


def test_owned_projection_toggle_respected() -> None:
    profile = load_style_profile(None)
    toggled = replace(profile.floor_plan, own_projection=True)
    assert geometry_projection.owned_projection_enabled(
        replace(profile, floor_plan=toggled)
    ) is True


def test_scaffold_returns_empty_when_enabled() -> None:
    """Until real implementation lands, the scaffold deliberately returns []."""
    profile = load_style_profile(None)
    toggled_floor_plan = replace(profile.floor_plan, own_projection=True, own_hidden=True)
    toggled = replace(profile, floor_plan=toggled_floor_plan)
    # Build minimally-valid dummy inputs; real implementation will use them.
    from ifc_book_prototype.domain import PlannedView
    view = PlannedView(
        view_id="test",
        sheet_id="A-100",
        title="Test",
        storey_name="L1",
        storey_elevation_m=0.0,
        cut_plane_m=1.1,
        view_depth_below_m=0.2,
        overhead_depth_above_m=2.3,
        included_classes=[],
    )
    assert geometry_projection.extract_owned_projection_lines(
        view=view, profile=toggled, elements=[], ifc_geom_module=None, storey_elevation_m=0.0
    ) == []
    assert geometry_projection.extract_owned_hidden_lines(
        view=view, profile=toggled, elements=[], ifc_geom_module=None, storey_elevation_m=0.0
    ) == []


def test_merge_owned_lines_suppresses_serializer_projection_when_asked() -> None:
    serializer_projected = TypedLine2D(
        kind=LineKind.PROJECTED,
        lineweight_class=LineweightClass.LIGHT,
        points=[Point2D(0, 0), Point2D(1, 0)],
        source_ifc_class="IfcWall",
    )
    cut_line = TypedLine2D(
        kind=LineKind.CUT,
        lineweight_class=LineweightClass.HEAVY,
        points=[Point2D(0, 0), Point2D(0, 1)],
        source_ifc_class="IfcWall",
    )
    owned_proj = TypedLine2D(
        kind=LineKind.PROJECTED,
        lineweight_class=LineweightClass.LIGHT,
        points=[Point2D(2, 2), Point2D(3, 3)],
        source_ifc_class="IfcColumn",
    )
    # Suppress on: serializer projected dropped, owned kept, cut kept.
    merged = geometry_projection.merge_owned_lines_into(
        [cut_line, serializer_projected],
        owned_projection=[owned_proj],
        owned_hidden=[],
        suppress_serializer_projection=True,
    )
    assert cut_line in merged
    assert owned_proj in merged
    assert serializer_projected not in merged

    # Suppress off: everything retained.
    merged_off = geometry_projection.merge_owned_lines_into(
        [cut_line, serializer_projected],
        owned_projection=[owned_proj],
        owned_hidden=[],
        suppress_serializer_projection=False,
    )
    assert cut_line in merged_off
    assert owned_proj in merged_off
    assert serializer_projected in merged_off
