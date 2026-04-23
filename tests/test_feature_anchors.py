from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from ifc_book_prototype.feature_anchors import build_feature_anchors_by_storey, count_feature_anchors


def _require_ifcopenshell():
    if importlib.util.find_spec("ifcopenshell") is None:
        pytest.skip("ifcopenshell is not installed")


def test_build_feature_anchors_finds_space_storey_mapping():
    _require_ifcopenshell()
    sample = Path("samples/Building-Architecture.ifc")
    if not sample.exists():
        pytest.skip("sample IFC not found")

    import ifcopenshell  # type: ignore
    from ifcopenshell.util.element import get_container  # type: ignore
    from ifcopenshell.util.unit import calculate_unit_scale  # type: ignore

    model = ifcopenshell.open(str(sample))
    anchors_by_storey = build_feature_anchors_by_storey(
        model=model,
        unit_scale=float(calculate_unit_scale(model)),
        get_container=get_container,
    )
    total_spaces = 0
    for anchors in anchors_by_storey.values():
        counts = count_feature_anchors(anchors)
        total_spaces += counts.get("IfcSpace", 0)
    assert total_spaces >= 1


def test_count_feature_anchors_is_deterministic_and_sorted():
    # Use tiny fake records by duck typing to avoid extra fixtures.
    class _A:
        def __init__(self, ifc_class):
            self.ifc_class = ifc_class

    anchors = [_A("IfcStair"), _A("IfcDoor"), _A("IfcDoor"), _A("IfcSpace")]
    counts = count_feature_anchors(anchors)
    assert list(counts.keys()) == ["IfcDoor", "IfcSpace", "IfcStair"]
    assert counts["IfcDoor"] == 2
