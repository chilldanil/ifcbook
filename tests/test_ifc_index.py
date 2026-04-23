from __future__ import annotations

from dataclasses import dataclass

from ifc_book_prototype._ifc_index import build_storey_elevations, index_elements_by_storey


@dataclass
class _FakeStorey:
    Name: str
    Elevation: float | None


@dataclass
class _FakeContainer:
    Name: str


class _FakeElement:
    def __init__(self, ifc_class: str, global_id: str, numeric_id: int, storey_name: str):
        self._ifc_class = ifc_class
        self.GlobalId = global_id
        self._id = numeric_id
        self._container = _FakeContainer(storey_name)

    def is_a(self):
        return self._ifc_class

    def id(self):
        return self._id


class _FakeModel:
    def __init__(self):
        self._data = {}

    def add(self, class_name: str, value):
        self._data.setdefault(class_name, []).append(value)

    def by_type(self, class_name: str):
        return list(self._data.get(class_name, []))


def _get_container(element):
    return element._container


def test_build_storey_elevations_scales_and_skips_invalid_names():
    model = _FakeModel()
    model.add("IfcBuildingStorey", _FakeStorey(Name=" Ground ", Elevation=3.5))
    model.add("IfcBuildingStorey", _FakeStorey(Name="", Elevation=9.0))
    model.add("IfcBuildingStorey", _FakeStorey(Name="Roof", Elevation=None))
    elevations = build_storey_elevations(model, unit_scale=0.001)
    assert elevations == {"Ground": 0.0035}


def test_index_elements_by_storey_is_deterministic():
    model = _FakeModel()
    elements = [
        _FakeElement("IfcWall", "B", 20, "L1"),
        _FakeElement("IfcWall", "A", 40, "L1"),
        _FakeElement("IfcSlab", "C", 10, "L1"),
        _FakeElement("IfcWall", "A", 10, "L1"),
        _FakeElement("IfcBeam", "X", 99, "L2"),
    ]
    for element in elements:
        model.add(element.is_a(), element)
    indexed = index_elements_by_storey(
        model,
        included_classes=["IfcWall", "IfcSlab", "IfcBeam"],
        get_container=_get_container,
    )
    assert sorted(indexed.keys()) == ["L1", "L2"]
    l1 = indexed["L1"]
    l1_keys = [(element.is_a(), element.GlobalId, element.id()) for element in l1]
    assert l1_keys == [
        ("IfcSlab", "C", 10),
        ("IfcWall", "A", 10),
        ("IfcWall", "A", 40),
        ("IfcWall", "B", 20),
    ]

