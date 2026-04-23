"""Phase 3B: default `cut_classes` covers IfcWall/IfcSlab/IfcColumn/IfcBeam/IfcMember.

These tests assert the profile contract — they don't require OCCT because the
routing is a pure filter over `profile.floor_plan.cut_classes` (see
``OCCTSectionBackend.build_view`` in ``geometry_occt.py``).
"""
from __future__ import annotations

from ifc_book_prototype.profiles import load_style_profile


EXPECTED_PHASE3B_CUT_CLASSES = {
    "IfcWall",
    "IfcSlab",
    "IfcColumn",
    "IfcBeam",
    "IfcMember",
}


def test_default_profile_cut_classes_phase3b() -> None:
    profile = load_style_profile(None)
    cut_classes = set(profile.floor_plan.cut_classes)
    assert EXPECTED_PHASE3B_CUT_CLASSES.issubset(cut_classes), (
        f"default profile cut_classes missing Phase 3B classes: "
        f"expected superset of {sorted(EXPECTED_PHASE3B_CUT_CLASSES)}, got {sorted(cut_classes)}"
    )


def test_cut_classes_subset_of_include_classes() -> None:
    """Everything routed through OCCT cut must also be in include_classes
    so the serializer fallback still has them available."""
    profile = load_style_profile(None)
    include = set(profile.floor_plan.include_classes)
    cut = set(profile.floor_plan.cut_classes)
    assert cut.issubset(include), (
        f"cut_classes must be a subset of include_classes: "
        f"extra in cut only = {sorted(cut - include)}"
    )
