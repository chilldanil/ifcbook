from __future__ import annotations

from ifc_book_prototype.domain import GeometrySummary
from ifc_book_prototype.geometry_metrics import summarize_geometry_runtime


def test_summarize_geometry_runtime_from_dataclasses():
    items = [
        GeometrySummary(
            view_id="v1",
            backend="composite-occt+serializer",
            cut_candidates={"IfcWall": 3},
            projection_candidates={"IfcSlab": 5},
            fallback_events=2,
            fallback_by_class={"IfcWall": 2},
            fallback_timeout_events=1,
            fallback_exception_events=1,
            fallback_empty_events=0,
            linework_counts={"CUT": 3, "PROJECTED": 7},
        ),
        GeometrySummary(
            view_id="v2",
            backend="ifcopenshell-svg-floorplan",
            cut_candidates={"IfcWall": 1},
            projection_candidates={"IfcSlab": 2},
            fallback_events=0,
            linework_counts={"PROJECTED": 2},
        ),
    ]
    summary = summarize_geometry_runtime(items)
    assert summary["view_count"] == 2
    assert summary["occt_view_count"] == 1
    assert summary["backend_counts"] == {
        "composite-occt+serializer": 1,
        "ifcopenshell-svg-floorplan": 1,
    }
    assert summary["fallback"]["events_total"] == 2
    assert summary["fallback"]["views_with_fallback"] == ["v1"]
    assert summary["fallback"]["by_class"] == {"IfcWall": 2}
    assert summary["linework_counts_total"] == {"CUT": 3, "PROJECTED": 9}
    assert summary["cut_candidates_total"] == {"IfcWall": 4}
    assert summary["projection_candidates_total"] == {"IfcSlab": 7}


def test_summarize_geometry_runtime_from_dicts():
    items = [
        {
            "view_id": "v1",
            "backend": "occt-section",
            "fallback_events": 1,
            "fallback_timeout_events": 1,
            "fallback_exception_events": 0,
            "fallback_empty_events": 1,
            "fallback_by_class": {"IfcSlab": 1},
            "linework_counts": {"CUT": 1},
        }
    ]
    summary = summarize_geometry_runtime(items)
    assert summary["view_count"] == 1
    assert summary["occt_view_count"] == 1
    assert summary["fallback"]["events_total"] == 1
    assert summary["fallback"]["timeout_events_total"] == 1
    assert summary["fallback"]["empty_events_total"] == 1
    assert summary["fallback"]["by_class"] == {"IfcSlab": 1}
    assert summary["linework_counts_total"] == {"CUT": 1}

