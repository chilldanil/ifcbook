from __future__ import annotations

from ifc_book_prototype.profiles import (
    available_profile_presets,
    load_style_profile,
    resolve_style_profile_path,
)


def test_profile_presets_are_discoverable_and_loadable():
    presets = available_profile_presets()

    assert {"default", "din_iso", "presentation", "permit_set", "coordination"} <= set(presets)
    for name in presets:
        profile = load_style_profile(name)
        assert profile.profile_id
        assert resolve_style_profile_path(name).exists()


def test_rerender_presets_have_distinct_style_knobs():
    presentation = load_style_profile("presentation")
    permit_set = load_style_profile("permit_set")
    coordination = load_style_profile("coordination")

    assert presentation.profile_id == "office_presentation_rerender_v1"
    assert permit_set.profile_id == "office_permit_set_rerender_v1"
    assert coordination.profile_id == "office_coordination_rerender_v1"
    assert presentation.lineweights_mm["cut_primary"] < permit_set.lineweights_mm["cut_primary"]
    assert coordination.lineweights_mm["projected"] > presentation.lineweights_mm["projected"]
    assert coordination.floor_plan.feature_overlay.doors_enabled is True
