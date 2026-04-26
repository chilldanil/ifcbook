from __future__ import annotations

from pathlib import Path

import pytest

try:
    from ifc_book_prototype.ui import (
        _default_benchmark_root,
        build_benchmark_request,
        build_runtime_gate_request,
        normalize_benchmark_root,
        parse_runtime_gate_thresholds,
    )
except RuntimeError as exc:  # pragma: no cover - host without Tcl/Tk.
    pytest.skip(str(exc), allow_module_level=True)


def test_parse_runtime_gate_thresholds_accepts_optional_fields() -> None:
    thresholds = parse_runtime_gate_thresholds(
        max_fallback_event_rate=" 0.25 ",
        max_timeout_events_total=" 2 ",
        min_occt_coverage_rate="",
        min_hidden_lines_total="  10",
        min_hidden_line_ratio="0.2",
    )

    assert thresholds.max_fallback_event_rate == pytest.approx(0.25)
    assert thresholds.max_timeout_events_total == 2
    assert thresholds.min_occt_coverage_rate is None
    assert thresholds.min_hidden_lines_total == 10
    assert thresholds.min_hidden_line_ratio == pytest.approx(0.2)


def test_parse_runtime_gate_thresholds_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="max_timeout_events_total must be an integer"):
        parse_runtime_gate_thresholds(
            max_fallback_event_rate="",
            max_timeout_events_total="1.5",
            min_occt_coverage_rate="",
            min_hidden_lines_total="",
            min_hidden_line_ratio="",
        )

    with pytest.raises(ValueError, match="min_occt_coverage_rate"):
        parse_runtime_gate_thresholds(
            max_fallback_event_rate="",
            max_timeout_events_total="",
            min_occt_coverage_rate="1.5",
            min_hidden_lines_total="",
            min_hidden_line_ratio="",
        )


def test_build_runtime_gate_request_requires_successful_run_dir_and_thresholds(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="successful pipeline run"):
        build_runtime_gate_request(
            last_output_dir=None,
            max_fallback_event_rate="",
            max_timeout_events_total="",
            min_occt_coverage_rate="",
            min_hidden_lines_total="",
            min_hidden_line_ratio="",
        )

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(ValueError, match="Set at least one runtime gate threshold"):
        build_runtime_gate_request(
            last_output_dir=run_dir,
            max_fallback_event_rate="",
            max_timeout_events_total="",
            min_occt_coverage_rate="",
            min_hidden_lines_total="",
            min_hidden_line_ratio="",
        )


def test_build_runtime_gate_request_builds_resolved_request(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    request = build_runtime_gate_request(
        last_output_dir=run_dir,
        max_fallback_event_rate="0.4",
        max_timeout_events_total="3",
        min_occt_coverage_rate="0.6",
        min_hidden_lines_total="5",
        min_hidden_line_ratio="0.1",
    )

    assert request.run_dir == run_dir.resolve()
    assert request.thresholds.max_fallback_event_rate == pytest.approx(0.4)
    assert request.thresholds.max_timeout_events_total == 3
    assert request.thresholds.min_occt_coverage_rate == pytest.approx(0.6)
    assert request.thresholds.min_hidden_lines_total == 5
    assert request.thresholds.min_hidden_line_ratio == pytest.approx(0.1)


def test_normalize_benchmark_root_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="required"):
        normalize_benchmark_root("  ")

    with pytest.raises(ValueError, match="does not exist"):
        normalize_benchmark_root(str(tmp_path / "missing"))

    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        normalize_benchmark_root(str(file_path))

    root = tmp_path / "bench"
    root.mkdir()
    normalized = normalize_benchmark_root(str(root))
    assert normalized == root.resolve()


def test_build_benchmark_request_uses_default_output_filenames(tmp_path: Path) -> None:
    root = tmp_path / "bench"
    root.mkdir()

    request = build_benchmark_request(benchmark_root=str(root))

    assert request.out_root == root.resolve()
    assert request.json_out == root.resolve() / "benchmark_summary.json"
    assert request.md_out == root.resolve() / "benchmark_summary.md"


def test_default_benchmark_root_uses_output_parent(tmp_path: Path) -> None:
    output_dir = tmp_path / "out" / "ui_run"
    expected = output_dir.parent.resolve()

    assert _default_benchmark_root(str(output_dir)) == str(expected)
