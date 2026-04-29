from __future__ import annotations

from typing import Dict, Iterable, Mapping


def summarize_geometry_runtime(geometry_items: Iterable[object]) -> dict:
    backend_counts: Dict[str, int] = {}
    fallback_by_class: Dict[str, int] = {}
    linework_counts_total: Dict[str, int] = {}
    cut_candidates_total: Dict[str, int] = {}
    projection_candidates_total: Dict[str, int] = {}
    views_with_fallback = []
    fallback_events_total = 0
    fallback_timeout_events_total = 0
    fallback_exception_events_total = 0
    fallback_empty_events_total = 0
    view_count = 0
    occt_view_count = 0
    owned_geometry = {
        "projection": _empty_owned_totals(),
        "hidden": _empty_owned_totals(),
    }

    for item in geometry_items:
        view_count += 1
        view_id = _field(item, "view_id", "")
        backend = _field(item, "backend", "")
        backend_counts[backend] = backend_counts.get(backend, 0) + 1

        fallback_events = int(_field(item, "fallback_events", 0) or 0)
        fallback_timeout = int(_field(item, "fallback_timeout_events", 0) or 0)
        fallback_exception = int(_field(item, "fallback_exception_events", 0) or 0)
        fallback_empty = int(_field(item, "fallback_empty_events", 0) or 0)
        fallback_events_total += fallback_events
        fallback_timeout_events_total += fallback_timeout
        fallback_exception_events_total += fallback_exception
        fallback_empty_events_total += fallback_empty
        if fallback_events > 0 and view_id:
            views_with_fallback.append(str(view_id))

        _merge_counts(fallback_by_class, _field(item, "fallback_by_class", {}))
        _merge_counts(linework_counts_total, _field(item, "linework_counts", {}))
        _merge_counts(cut_candidates_total, _field(item, "cut_candidates", {}))
        _merge_counts(projection_candidates_total, _field(item, "projection_candidates", {}))
        if _is_occt_covered_view(item, backend, fallback_events):
            occt_view_count += 1
        _merge_owned_geometry(owned_geometry, _field(item, "owned_geometry_telemetry", {}))

    return {
        "view_count": view_count,
        "backend_counts": dict(sorted(backend_counts.items())),
        "occt_view_count": occt_view_count,
        "occt_coverage_view_count": occt_view_count,
        "fallback": {
            "events_total": fallback_events_total,
            "views_with_fallback_count": len(views_with_fallback),
            "views_with_fallback": sorted(set(views_with_fallback)),
            "timeout_events_total": fallback_timeout_events_total,
            "exception_events_total": fallback_exception_events_total,
            "empty_events_total": fallback_empty_events_total,
            "by_class": dict(sorted(fallback_by_class.items())),
        },
        "linework_counts_total": dict(sorted(linework_counts_total.items())),
        "cut_candidates_total": dict(sorted(cut_candidates_total.items())),
        "projection_candidates_total": dict(sorted(projection_candidates_total.items())),
        "owned_geometry": owned_geometry,
    }


def _field(item: object, name: str, default):
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _merge_counts(target: Dict[str, int], source: object) -> None:
    if not isinstance(source, Mapping):
        return
    for key, raw_value in source.items():
        key_s = str(key)
        value = int(raw_value)
        target[key_s] = target.get(key_s, 0) + value


def _is_occt_covered_view(item: object, backend: object, fallback_events: int) -> bool:
    if "occt" not in str(backend).lower():
        return False
    linework_counts: Dict[str, int] = {}
    _merge_counts(linework_counts, _field(item, "linework_counts", {}))
    if sum(linework_counts.values()) > 0:
        return True
    return fallback_events > 0


def _empty_owned_totals() -> dict:
    return {
        "attempted_elements": 0,
        "emitted_lines": 0,
        "skipped_elements": 0,
        "failed_elements": 0,
        "attempted_by_class": {},
        "emitted_by_class": {},
        "skipped_by_class": {},
        "failed_by_class": {},
    }


def _merge_owned_geometry(target: dict, source: object) -> None:
    if not isinstance(source, Mapping):
        return
    for kind in ("projection", "hidden"):
        kind_source = source.get(kind, {})
        if not isinstance(kind_source, Mapping):
            continue
        kind_target = target[kind]
        for key in ("attempted_elements", "emitted_lines", "skipped_elements", "failed_elements"):
            kind_target[key] += int(kind_source.get(key, 0) or 0)
        for key in ("attempted_by_class", "emitted_by_class", "skipped_by_class", "failed_by_class"):
            _merge_counts(kind_target[key], kind_source.get(key, {}))
