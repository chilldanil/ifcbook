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


def test_summarize_geometry_runtime_does_not_cover_empty_occt_elevation():
    summary = summarize_geometry_runtime(
        [
            {
                "view_id": "elevation_north",
                "backend": "occt-elevation-edges",
                "source_elements": 0,
                "linework_counts": {},
                "fallback_events": 0,
            },
            {
                "view_id": "floor_plan_01",
                "backend": "composite-occt+serializer",
                "linework_counts": {"CUT": 1},
                "fallback_events": 0,
            },
        ]
    )

    assert summary["view_count"] == 2
    assert summary["backend_counts"]["occt-elevation-edges"] == 1
    assert summary["occt_view_count"] == 1
    assert summary["occt_coverage_view_count"] == 1


def test_summarize_geometry_runtime_aggregates_owned_geometry_telemetry():
    summary = summarize_geometry_runtime(
        [
            {
                "view_id": "floor_plan_01",
                "backend": "composite-occt+serializer",
                "linework_counts": {"CUT": 1},
                "owned_geometry_telemetry": {
                    "projection": {
                        "attempted_elements": 3,
                        "emitted_lines": 2,
                        "skipped_elements": 1,
                        "failed_elements": 0,
                        "attempted_by_class": {"IfcWall": 3},
                        "emitted_by_class": {"IfcWall": 2},
                        "skipped_by_class": {"IfcWall": 1},
                        "failed_by_class": {},
                    },
                    "hidden": {
                        "attempted_elements": 3,
                        "emitted_lines": 1,
                        "skipped_elements": 1,
                        "failed_elements": 1,
                        "attempted_by_class": {"IfcWall": 3},
                        "emitted_by_class": {"IfcWall": 1},
                        "skipped_by_class": {"IfcWall": 1},
                        "failed_by_class": {"IfcWall": 1},
                    },
                },
            }
        ]
    )

    assert summary["owned_geometry"]["projection"]["attempted_elements"] == 3
    assert summary["owned_geometry"]["projection"]["emitted_by_class"] == {"IfcWall": 2}
    assert summary["owned_geometry"]["hidden"]["failed_elements"] == 1
    assert summary["owned_geometry"]["hidden"]["failed_by_class"] == {"IfcWall": 1}
