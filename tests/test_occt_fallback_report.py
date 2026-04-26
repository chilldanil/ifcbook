from __future__ import annotations

from ifc_book_prototype import occt_section


class _FakeElement:
    def __init__(self, ifc_class: str, gid: str, numeric_id: int):
        self._ifc_class = ifc_class
        self.GlobalId = gid
        self._id = numeric_id

    def is_a(self):
        return self._ifc_class

    def id(self):
        return self._id


def test_extract_cut_lines_report_tracks_timeout_fallback(monkeypatch):
    monkeypatch.setattr(occt_section, "_require_occt", lambda: None)
    monkeypatch.setattr(occt_section, "build_cut_face", lambda plane, extent: object())

    def _always_timeout(fn, budget_s):  # noqa: ARG001
        raise occt_section.BudgetExceeded("timeout")

    monkeypatch.setattr(occt_section, "run_with_budget", _always_timeout)

    calls = []

    def _fallback(element, plane_z):
        calls.append((element.GlobalId, plane_z))
        if element.is_a() == "IfcWall":
            return [[(0.0, 0.0), (1.0, 0.0)]]
        return []

    elements = [
        _FakeElement("IfcSlab", "S1", 2),
        _FakeElement("IfcWall", "W1", 1),
    ]
    report = occt_section.extract_cut_lines_report(
        ifc_geom_module=None,
        elements=elements,
        plane=occt_section.CutPlane(z_m=1.1),
        per_element_budget_s=0.2,
        chord_tol_m=5.0e-4,
        fallback=_fallback,
    )

    assert calls == [("S1", 1.1), ("W1", 1.1)]
    assert report.fallback_events == 2
    assert report.fallback_timeout_events == 2
    assert report.fallback_exception_events == 0
    assert report.fallback_empty_events == 1
    assert report.fallback_line_count == 1
    assert report.fallback_by_class == {"IfcSlab": 1, "IfcWall": 1}
    assert len(report.lines) == 1
    assert report.lines[0].source_ifc_class == "IfcWall"
    assert any("timed out" in note for note in report.lines[0].notes)


def test_extract_cut_lines_report_tracks_exception_fallback(monkeypatch):
    monkeypatch.setattr(occt_section, "_require_occt", lambda: None)
    monkeypatch.setattr(occt_section, "build_cut_face", lambda plane, extent: object())

    def _always_error(fn, budget_s):  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr(occt_section, "run_with_budget", _always_error)

    called = []

    def _fallback(element):
        called.append(element.GlobalId)
        return [[(0.0, 0.0), (0.0, 1.0)]]

    report = occt_section.extract_cut_lines_report(
        ifc_geom_module=None,
        elements=[_FakeElement("IfcWall", "W1", 1)],
        plane=occt_section.CutPlane(z_m=0.0),
        per_element_budget_s=0.2,
        chord_tol_m=5.0e-4,
        fallback=_fallback,
    )

    assert called == ["W1"]
    assert report.fallback_events == 1
    assert report.fallback_timeout_events == 0
    assert report.fallback_exception_events == 1
    assert report.fallback_empty_events == 0
    assert report.fallback_by_class == {"IfcWall": 1}
    assert len(report.lines) == 1
    assert any("raised RuntimeError" in note for note in report.lines[0].notes)


def test_brep_from_ifc_element_accepts_direct_opencascade_geometry(monkeypatch):
    monkeypatch.setattr(occt_section, "_require_occt", lambda: None)

    class _FakeSettings:
        def set(self, key, value):  # noqa: ARG002
            return None

    class _FakeShape:
        def IsNull(self):
            return False

    class _FakeShapeTuple:
        def __init__(self):
            self.geometry = _FakeShape()

    class _FakeIfcGeom:
        def settings(self):
            return _FakeSettings()

        def create_shape(self, settings, element):  # noqa: ARG002
            return _FakeShapeTuple()

    shape = occt_section.brep_from_ifc_element(_FakeIfcGeom(), None, object())
    assert shape is not None
    assert hasattr(shape, "IsNull")


def test_brep_from_ifc_element_uses_brep_data_fallback_when_needed(monkeypatch):
    monkeypatch.setattr(occt_section, "_require_occt", lambda: None)
    marker = object()
    monkeypatch.setattr(occt_section, "_read_brep_text_to_shape", lambda brep_data: marker)

    class _FakeSettings:
        def set(self, key, value):  # noqa: ARG002
            return None

    class _FakeGeometry:
        brep_data = "BREP-DATA"

    class _FakeShapeTuple:
        def __init__(self):
            self.geometry = _FakeGeometry()

    class _FakeIfcGeom:
        def settings(self):
            return _FakeSettings()

        def create_shape(self, settings, element):  # noqa: ARG002
            return _FakeShapeTuple()

    shape = occt_section.brep_from_ifc_element(_FakeIfcGeom(), None, object())
    assert shape is marker
