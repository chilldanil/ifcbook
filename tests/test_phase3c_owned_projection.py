"""Phase 3C: owned projection/hidden scaffolding.

These tests verify the contract surface only. Actual owned projection/hidden
line generation lands later; the scaffolding here just has to be honest about
its gates and not break the default path.
"""
from __future__ import annotations

from dataclasses import replace
import pytest
from ifc_book_prototype import geometry_projection
from ifc_book_prototype.domain import LineKind, LineweightClass, PlannedView, Point2D, TypedLine2D
from ifc_book_prototype.profiles import PACKAGE_ROOT, load_style_profile


def _view() -> PlannedView:
    return PlannedView(
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


class _FakeElement:
    def __init__(self, gid: str, ifc_class: str = "IfcWall", numeric_id: int = 1):
        self.GlobalId = gid
        self._ifc_class = ifc_class
        self._id = numeric_id

    def is_a(self):
        return self._ifc_class

    def id(self):
        return self._id


class _FakeCompound:
    def __init__(self, *, edges=None, is_null: bool = False):
        self.edges = list(edges or [])
        self._is_null = is_null

    def IsNull(self):
        return self._is_null


class _InvalidCompound:
    raise_in_explorer = True


def _patch_hidden_hlr(
    monkeypatch,
    *,
    compounds_by_getter: dict[str, object],
    edge_to_polyline_3d: dict[str, list[tuple[float, float, float]]],
) -> None:
    class _FakeAlgo:
        def Add(self, shape):  # noqa: ARG002
            return None

        def Projector(self, projector):  # noqa: ARG002
            return None

        def Update(self):
            return None

        def Hide(self):
            return None

    class _FakeHLRShape:
        def HCompound(self):
            return compounds_by_getter.get("HCompound")

        def OutLineHCompound(self):
            return compounds_by_getter.get("OutLineHCompound")

        def Rg1LineHCompound(self):
            return compounds_by_getter.get("Rg1LineHCompound")

        def RgNLineHCompound(self):
            return compounds_by_getter.get("RgNLineHCompound")

    class _FakeExplorer:
        def __init__(self, compound, _edge_kind):  # noqa: ANN001
            if getattr(compound, "raise_in_explorer", False):
                raise RuntimeError("invalid compound")
            self._edges = list(getattr(compound, "edges", []))
            self._idx = 0

        def More(self):
            return self._idx < len(self._edges)

        def Current(self):
            return self._edges[self._idx]

        def Next(self):
            self._idx += 1

    monkeypatch.setattr(geometry_projection.occt_section, "OCCT_AVAILABLE", True)
    monkeypatch.setattr(
        geometry_projection.occt_section,
        "brep_from_ifc_element",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        geometry_projection.occt_section,
        "edge_to_polyline_3d",
        lambda edge, _tol: edge_to_polyline_3d[edge],
    )
    monkeypatch.setattr(
        geometry_projection.occt_section,
        "chain_polylines",
        lambda polylines: [list(polyline) for polyline in polylines],
    )
    monkeypatch.setattr(
        geometry_projection,
        "_import_hlr_primitives",
        lambda: (
            _FakeAlgo,
            lambda _algo: _FakeHLRShape(),
            lambda *_args: object(),
            lambda *_args: object(),
            lambda *_args: object(),
            lambda *_args: object(),
            _FakeExplorer,
            object(),
        ),
    )


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
    """When OCCT is unavailable, owned projection/hidden return empty output."""
    profile = load_style_profile(None)
    toggled_floor_plan = replace(profile.floor_plan, own_projection=True, own_hidden=True)
    toggled = replace(profile, floor_plan=toggled_floor_plan)
    view = _view()
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
    serializer_hidden = TypedLine2D(
        kind=LineKind.HIDDEN,
        lineweight_class=LineweightClass.LIGHT,
        points=[Point2D(0, 1), Point2D(1, 1)],
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
        [cut_line, serializer_projected, serializer_hidden],
        owned_projection=[owned_proj],
        owned_hidden=[],
        suppress_serializer_projection=True,
    )
    assert cut_line in merged
    assert owned_proj in merged
    assert serializer_hidden in merged
    assert serializer_projected not in merged

    # Suppress off: everything retained.
    merged_off = geometry_projection.merge_owned_lines_into(
        [cut_line, serializer_projected, serializer_hidden],
        owned_projection=[owned_proj],
        owned_hidden=[],
        suppress_serializer_projection=False,
    )
    assert cut_line in merged_off
    assert owned_proj in merged_off
    assert serializer_hidden in merged_off
    assert serializer_projected in merged_off


def test_merge_owned_lines_drops_hidden_duplicates_of_visible_geometry() -> None:
    visible_projected = TypedLine2D(
        kind=LineKind.PROJECTED,
        lineweight_class=LineweightClass.LIGHT,
        points=[Point2D(0.0, 0.0), Point2D(2.0, 0.0)],
        source_ifc_class="IfcWall",
    )
    hidden_duplicate = TypedLine2D(
        kind=LineKind.HIDDEN,
        lineweight_class=LineweightClass.FINE,
        points=[Point2D(2.0, 0.0), Point2D(0.0, 0.0)],
        source_ifc_class="IfcWall",
    )
    hidden_unique = TypedLine2D(
        kind=LineKind.HIDDEN,
        lineweight_class=LineweightClass.FINE,
        points=[Point2D(3.0, 0.0), Point2D(4.0, 0.0)],
        source_ifc_class="IfcWall",
    )
    merged = geometry_projection.merge_owned_lines_into(
        [visible_projected],
        owned_projection=[],
        owned_hidden=[hidden_duplicate, hidden_unique],
        suppress_serializer_projection=False,
    )
    assert visible_projected in merged
    assert hidden_duplicate not in merged
    assert hidden_unique in merged


def test_clip_polyline_3d_to_z_band_trims_outside_segments() -> None:
    clipped = geometry_projection._clip_polyline_3d_to_z_band(
        polyline_3d=[
            (0.0, 0.0, -1.0),
            (1.0, 0.0, 0.5),
            (2.0, 0.0, 2.0),
            (3.0, 0.0, 4.0),
        ],
        z_low=0.0,
        z_high=3.0,
    )
    assert len(clipped) == 3
    assert clipped[0][0][0] == pytest.approx(0.66667, abs=1.0e-5)
    assert clipped[0][1] == (1.0, 0.0)
    assert clipped[2][0] == (2.0, 0.0)
    assert clipped[2][1][0] == pytest.approx(2.5, abs=1.0e-5)


def test_extract_owned_projection_passes_view_band_limits(monkeypatch) -> None:
    profile = load_style_profile(None)
    profile = replace(profile, floor_plan=replace(profile.floor_plan, own_projection=True))
    view = _view()
    captured = {}

    monkeypatch.setattr(geometry_projection.occt_section, "OCCT_AVAILABLE", True)
    monkeypatch.setattr(geometry_projection.occt_section, "run_with_budget", lambda fn, _: fn())

    def _fake_project(
        ifc_geom_module,
        element,
        chord_tol_m,
        cut_plane_z,
        view_band_low_z,
        view_band_high_z,
    ):
        captured["ifc_geom_module"] = ifc_geom_module
        captured["element_id"] = element.id()
        captured["chord_tol_m"] = chord_tol_m
        captured["cut_plane_z"] = cut_plane_z
        captured["view_band_low_z"] = view_band_low_z
        captured["view_band_high_z"] = view_band_high_z
        return [[(0.0, 0.0), (1.0, 0.0)]]

    monkeypatch.setattr(geometry_projection, "_project_edges_of_element", _fake_project)

    lines = geometry_projection.extract_owned_projection_lines(
        view=view,
        profile=profile,
        elements=[_FakeElement("W-1", numeric_id=77)],
        ifc_geom_module="geom",
        storey_elevation_m=10.0,
    )

    assert len(lines) == 1
    assert lines[0].kind is LineKind.PROJECTED
    assert captured["element_id"] == 77
    assert captured["ifc_geom_module"] == "geom"
    assert captured["cut_plane_z"] == pytest.approx(11.1)
    assert captured["view_band_low_z"] == pytest.approx(9.8)
    assert captured["view_band_high_z"] == pytest.approx(13.4)


def test_extract_owned_hidden_lines_best_effort_hlr(monkeypatch) -> None:
    profile = load_style_profile(None)
    profile = replace(profile, floor_plan=replace(profile.floor_plan, own_hidden=True))
    view = _view()

    monkeypatch.setattr(geometry_projection.occt_section, "OCCT_AVAILABLE", True)
    monkeypatch.setattr(geometry_projection.occt_section, "run_with_budget", lambda fn, _: fn())
    monkeypatch.setattr(
        geometry_projection,
        "_hidden_edges_of_element",
        lambda **_: [[(0.0, 0.0), (1.0, 0.0)]],
    )

    lines = geometry_projection.extract_owned_hidden_lines(
        view=view,
        profile=profile,
        elements=[_FakeElement("W-1", ifc_class="IfcWall", numeric_id=2)],
        ifc_geom_module="geom",
        storey_elevation_m=0.0,
    )

    assert len(lines) == 1
    assert lines[0].kind is LineKind.HIDDEN
    assert lines[0].lineweight_class is LineweightClass.FINE
    assert lines[0].source_ifc_class == "IfcWall"
    assert lines[0].source_element == "W-1"


def test_extract_owned_projection_deduplicates_reversed_duplicates(monkeypatch) -> None:
    profile = load_style_profile(None)
    profile = replace(profile, floor_plan=replace(profile.floor_plan, own_projection=True))
    view = _view()

    monkeypatch.setattr(geometry_projection.occt_section, "OCCT_AVAILABLE", True)
    monkeypatch.setattr(geometry_projection.occt_section, "run_with_budget", lambda fn, _: fn())

    def _fake_project(
        ifc_geom_module,  # noqa: ARG001
        element,
        chord_tol_m,  # noqa: ARG001
        cut_plane_z,  # noqa: ARG001
        view_band_low_z,  # noqa: ARG001
        view_band_high_z,  # noqa: ARG001
    ):
        if element.GlobalId == "A":
            return [[(0.0, 0.0), (1.0, 0.0)]]
        return [[(1.0, 0.0), (0.0, 0.0)]]

    monkeypatch.setattr(geometry_projection, "_project_edges_of_element", _fake_project)

    lines = geometry_projection.extract_owned_projection_lines(
        view=view,
        profile=profile,
        elements=[
            _FakeElement("B", ifc_class="IfcWall", numeric_id=2),
            _FakeElement("A", ifc_class="IfcWall", numeric_id=1),
        ],
        ifc_geom_module="geom",
        storey_elevation_m=0.0,
    )

    assert len(lines) == 1
    assert lines[0].source_element == "A"
    assert lines[0].source_ifc_class == "IfcWall"


def test_extract_owned_hidden_deduplicates_reversed_duplicates(monkeypatch) -> None:
    profile = load_style_profile(None)
    profile = replace(profile, floor_plan=replace(profile.floor_plan, own_hidden=True))
    view = _view()

    monkeypatch.setattr(geometry_projection.occt_section, "OCCT_AVAILABLE", True)
    monkeypatch.setattr(geometry_projection.occt_section, "run_with_budget", lambda fn, _: fn())

    def _fake_hidden(
        *,
        ifc_geom_module,  # noqa: ARG001
        element,
        chord_tol_m,  # noqa: ARG001
        view_band_low_z,  # noqa: ARG001
        view_band_high_z,  # noqa: ARG001
    ):
        if element.GlobalId == "A":
            return [[(0.0, 0.0), (0.0, 1.0)]]
        return [[(0.0, 1.0), (0.0, 0.0)]]

    monkeypatch.setattr(geometry_projection, "_hidden_edges_of_element", _fake_hidden)

    lines = geometry_projection.extract_owned_hidden_lines(
        view=view,
        profile=profile,
        elements=[
            _FakeElement("B", ifc_class="IfcWall", numeric_id=2),
            _FakeElement("A", ifc_class="IfcWall", numeric_id=1),
        ],
        ifc_geom_module="geom",
        storey_elevation_m=0.0,
    )

    assert len(lines) == 1
    assert lines[0].kind is LineKind.HIDDEN
    assert lines[0].source_element == "A"
    assert lines[0].source_ifc_class == "IfcWall"


def test_hidden_edges_consumes_all_available_hidden_compounds(monkeypatch) -> None:
    _patch_hidden_hlr(
        monkeypatch,
        compounds_by_getter={
            "HCompound": _FakeCompound(edges=["edge_a"]),
            "OutLineHCompound": _FakeCompound(edges=["edge_b"]),
            "Rg1LineHCompound": None,
            "RgNLineHCompound": None,
        },
        edge_to_polyline_3d={
            "edge_a": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
            "edge_b": [(2.0, 0.0, 0.0), (3.0, 0.0, 0.0)],
        },
    )

    lines = geometry_projection._hidden_edges_of_element(
        ifc_geom_module="geom",
        element=_FakeElement("W-1"),
        chord_tol_m=0.01,
        view_band_low_z=-1.0,
        view_band_high_z=1.0,
    )

    assert len(lines) == 2
    assert lines[0][0] == pytest.approx((0.0, 0.0))
    assert lines[0][1] == pytest.approx((1.0, 0.0))
    assert lines[1][0] == pytest.approx((2.0, 0.0))
    assert lines[1][1] == pytest.approx((3.0, 0.0))


def test_hidden_edges_skips_null_and_invalid_compounds(monkeypatch) -> None:
    _patch_hidden_hlr(
        monkeypatch,
        compounds_by_getter={
            "HCompound": None,
            "OutLineHCompound": _FakeCompound(edges=["ignored_null"], is_null=True),
            "Rg1LineHCompound": _InvalidCompound(),
            "RgNLineHCompound": _FakeCompound(edges=["edge_valid"]),
        },
        edge_to_polyline_3d={
            "edge_valid": [(5.0, 0.0, 0.0), (6.0, 0.0, 0.0)],
        },
    )

    lines = geometry_projection._hidden_edges_of_element(
        ifc_geom_module="geom",
        element=_FakeElement("W-2"),
        chord_tol_m=0.01,
        view_band_low_z=-1.0,
        view_band_high_z=1.0,
    )

    assert len(lines) == 1
    assert lines[0][0] == pytest.approx((5.0, 0.0))
    assert lines[0][1] == pytest.approx((6.0, 0.0))


def test_hidden_edges_dedup_is_deterministic_across_compounds(monkeypatch) -> None:
    _patch_hidden_hlr(
        monkeypatch,
        compounds_by_getter={
            "HCompound": _FakeCompound(edges=["edge_a"]),
            "OutLineHCompound": _FakeCompound(edges=["edge_b"]),
            "Rg1LineHCompound": _FakeCompound(edges=["edge_c"]),
            "RgNLineHCompound": None,
        },
        edge_to_polyline_3d={
            "edge_a": [(1.0, 0.0, 0.0), (0.0, 0.0, 0.0)],
            "edge_b": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
            "edge_c": [(2.0, 0.0, 0.0), (3.0, 0.0, 0.0)],
        },
    )

    lines_first = geometry_projection._hidden_edges_of_element(
        ifc_geom_module="geom",
        element=_FakeElement("W-3"),
        chord_tol_m=0.01,
        view_band_low_z=-1.0,
        view_band_high_z=1.0,
    )
    lines_second = geometry_projection._hidden_edges_of_element(
        ifc_geom_module="geom",
        element=_FakeElement("W-3"),
        chord_tol_m=0.01,
        view_band_low_z=-1.0,
        view_band_high_z=1.0,
    )

    assert len(lines_first) == 2
    assert lines_first[0][0] == pytest.approx((0.0, 0.0))
    assert lines_first[0][1] == pytest.approx((1.0, 0.0))
    assert lines_first[1][0] == pytest.approx((2.0, 0.0))
    assert lines_first[1][1] == pytest.approx((3.0, 0.0))
    assert lines_second == lines_first


def test_hidden_edges_accept_projector_space_z0_output_when_band_is_elsewhere(monkeypatch) -> None:
    _patch_hidden_hlr(
        monkeypatch,
        compounds_by_getter={
            "HCompound": _FakeCompound(edges=["edge_proj"]),
            "OutLineHCompound": None,
            "Rg1LineHCompound": None,
            "RgNLineHCompound": None,
        },
        edge_to_polyline_3d={
            "edge_proj": [(10.0, 0.0, 0.0), (11.0, 0.0, 0.0)],
        },
    )

    lines = geometry_projection._hidden_edges_of_element(
        ifc_geom_module="geom",
        element=_FakeElement("W-4"),
        chord_tol_m=0.01,
        view_band_low_z=10.0,
        view_band_high_z=12.0,
    )

    assert len(lines) == 1
    assert lines[0][0] == pytest.approx((10.0, 0.0))
    assert lines[0][1] == pytest.approx((11.0, 0.0))


def test_phase3c_profile_enables_owned_projection() -> None:
    profile_path = PACKAGE_ROOT / "profiles" / "din_iso_arch_floor_plan_v3_phase3c_owned_projection.json"
    profile = load_style_profile(str(profile_path))
    assert profile.floor_plan.own_projection is True
    assert profile.floor_plan.own_hidden is False


def test_phase3c_hidden_profile_enables_owned_hidden() -> None:
    profile_path = (
        PACKAGE_ROOT
        / "profiles"
        / "din_iso_arch_floor_plan_v3_phase3c_owned_projection_hidden.json"
    )
    profile = load_style_profile(str(profile_path))
    assert profile.floor_plan.own_projection is True
    assert profile.floor_plan.own_hidden is True
