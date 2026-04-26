from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from ifc_book_prototype.feature_anchors import (
    _extract_direction_xy_for_feature,
    _extract_label,
    build_feature_anchors_by_storey,
    count_feature_anchors,
)


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


def test_extract_door_semantic_swing_hint_from_operation_type():
    class _Door:
        def __init__(self, operation_type=None, user_defined_operation_type=None):
            self.OperationType = operation_type
            self.UserDefinedOperationType = user_defined_operation_type

    left = _Door(operation_type="SINGLE_SWING_LEFT")
    right = _Door(operation_type="DOUBLE_DOOR_SINGLE_SWING_RIGHT")
    assert _extract_label(left, "IfcDoor") == "door_swing:left"
    assert _extract_label(right, "IfcDoor") == "door_swing:right"


def test_extract_door_semantic_swing_hint_falls_back_to_user_defined_operation_type():
    class _Door:
        def __init__(self, operation_type=None, user_defined_operation_type=None):
            self.OperationType = operation_type
            self.UserDefinedOperationType = user_defined_operation_type

    left = _Door(operation_type="USERDEFINED", user_defined_operation_type="left hand")
    right = _Door(operation_type=None, user_defined_operation_type="RH")
    unknown = _Door(operation_type="NOTDEFINED", user_defined_operation_type="center")

    assert _extract_label(left, "IfcDoor") == "door_swing:left"
    assert _extract_label(right, "IfcDoor") == "door_swing:right"
    assert _extract_label(unknown, "IfcDoor") is None


def test_extract_door_semantic_swing_hint_from_predefined_type():
    class _Door:
        def __init__(self, predefined_type=None):
            self.OperationType = None
            self.UserDefinedOperationType = None
            self.PredefinedType = predefined_type

    left = _Door(predefined_type="DOUBLE_DOOR_SINGLE_SWING_LEFT")
    right = _Door(predefined_type="SINGLE_SWING_RIGHT")
    assert _extract_label(left, "IfcDoor") == "door_swing:left"
    assert _extract_label(right, "IfcDoor") == "door_swing:right"


def test_extract_door_semantic_swing_hint_from_property_set():
    class _Wrapped:
        def __init__(self, value):
            self.wrappedValue = value

    class _Property:
        def __init__(self, name: str, value: str):
            self.Name = name
            self.NominalValue = _Wrapped(value)
            self.EnumerationValues = []
            self.ListValues = []

    class _PropertySet:
        def __init__(self, properties):
            self.HasProperties = properties

    class _RelDefines:
        def __init__(self, prop_set):
            self.RelatingPropertyDefinition = prop_set

    class _Door:
        def __init__(self, properties):
            self.OperationType = None
            self.UserDefinedOperationType = None
            self.PredefinedType = None
            self.ObjectType = None
            self.Name = None
            self.IsDefinedBy = [_RelDefines(_PropertySet(properties))]

    door = _Door([_Property("DoorHanding", "RH")])
    assert _extract_label(door, "IfcDoor") == "door_swing:right"


def test_extract_space_label_combines_number_and_name_from_ifc_fields():
    class _Space:
        Number = "101"
        Name = "Kitchen"
        LongName = None
        Reference = None
        Tag = None
        ObjectType = None
        IsDefinedBy = []

    assert _extract_label(_Space(), "IfcSpace") == "101 Kitchen"


def test_extract_space_label_uses_property_set_when_attributes_missing():
    class _Wrapped:
        def __init__(self, value):
            self.wrappedValue = value

    class _Property:
        def __init__(self, name: str, value: str):
            self.Name = name
            self.NominalValue = _Wrapped(value)
            self.EnumerationValues = []
            self.ListValues = []

    class _PropertySet:
        def __init__(self, properties):
            self.HasProperties = properties

    class _RelDefines:
        def __init__(self, prop_set):
            self.RelatingPropertyDefinition = prop_set

    class _Space:
        LongName = None
        Name = None
        ObjectType = None
        Number = None
        Reference = None
        Tag = None

        def __init__(self):
            self.IsDefinedBy = [
                _RelDefines(
                    _PropertySet(
                        [
                            _Property("RoomNumber", "A-12"),
                            _Property("RoomName", "Lobby"),
                        ]
                    )
                )
            ]

    assert _extract_label(_Space(), "IfcSpace") == "A-12 Lobby"


class _MockEntity:
    _id_seq = 1

    def __init__(self, ifc_class: str, **attrs):
        self._ifc_class = ifc_class
        self._id = _MockEntity._id_seq
        _MockEntity._id_seq += 1
        for key, value in attrs.items():
            setattr(self, key, value)

    def is_a(self, name=None):
        if name is None:
            return self._ifc_class
        return self._ifc_class == name

    def id(self):
        return self._id


def _point(x: float, y: float):
    return _MockEntity("IfcCartesianPoint", Coordinates=(x, y, 0.0))


def _axis_polyline_representation(points):
    polyline = _MockEntity("IfcPolyline", Points=[_point(x, y) for x, y in points])
    axis = _MockEntity("IfcShapeRepresentation", RepresentationIdentifier="Axis", Items=[polyline])
    return _MockEntity("IfcProductDefinitionShape", Representations=[axis])


def _path_polyline_representation(points):
    polyline = _MockEntity("IfcPolyline", Points=[_point(x, y) for x, y in points])
    axis = _MockEntity(
        "IfcShapeRepresentation",
        RepresentationIdentifier="Path",
        RepresentationType="Curve2D",
        Items=[polyline],
    )
    return _MockEntity("IfcProductDefinitionShape", Representations=[axis])


def _placement_matrix(dir_x: float, dir_y: float):
    return [
        [dir_x, 0.0, 0.0, 0.0],
        [dir_y, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def test_stair_flight_axis_polyline_point_order_drives_direction():
    matrix = _placement_matrix(0.0, 1.0)
    forward = _MockEntity("IfcStairFlight", Representation=_axis_polyline_representation([(0.0, 0.0), (4.0, 0.0)]))
    reverse = _MockEntity("IfcStairFlight", Representation=_axis_polyline_representation([(4.0, 0.0), (0.0, 0.0)]))

    dir_forward = _extract_direction_xy_for_feature(forward, "IfcStairFlight", matrix, unit_scale=1.0)
    dir_reverse = _extract_direction_xy_for_feature(reverse, "IfcStairFlight", matrix, unit_scale=1.0)

    assert dir_forward == pytest.approx((1.0, 0.0))
    assert dir_reverse == pytest.approx((-1.0, 0.0))


def test_ifc_stair_inherits_semantic_direction_from_related_flight():
    matrix = _placement_matrix(1.0, 0.0)
    flight = _MockEntity("IfcStairFlight", Representation=_axis_polyline_representation([(0.0, 0.0), (0.0, 3.0)]))
    relation = _MockEntity("IfcRelAggregates", RelatedObjects=[flight])
    stair = _MockEntity("IfcStair", IsDecomposedBy=[relation], Representation=None)

    direction = _extract_direction_xy_for_feature(stair, "IfcStair", matrix, unit_scale=1.0)
    assert direction == pytest.approx((0.0, 1.0))


def test_stair_falls_back_to_placement_direction_when_semantics_missing():
    matrix = _placement_matrix(0.0, -2.0)
    stair = _MockEntity("IfcStair", Representation=None, IsDecomposedBy=[])

    direction = _extract_direction_xy_for_feature(stair, "IfcStair", matrix, unit_scale=1.0)
    assert direction == pytest.approx((0.0, -1.0))


def test_stair_path_representation_is_accepted_for_semantic_direction():
    matrix = _placement_matrix(0.0, 1.0)
    stair = _MockEntity("IfcStair", Representation=_path_polyline_representation([(2.0, 0.0), (5.0, 0.0)]))

    direction = _extract_direction_xy_for_feature(stair, "IfcStair", matrix, unit_scale=1.0)
    assert direction == pytest.approx((1.0, 0.0))
