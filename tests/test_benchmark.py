from __future__ import annotations

import json
from pathlib import Path

from ifc_book_prototype import benchmark


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_run(
    out_root: Path,
    sample: str,
    *,
    view_count: int,
    occt_view_count: int,
    fallback_events_total: int,
    timeout_events_total: int,
    linework_counts_total: dict[str, int] | None = None,
    gate_status: str | None = None,
    runtime_s: float | None = None,
) -> Path:
    run_dir = out_root / sample
    summary_payload = {
        "view_count": view_count,
        "occt_view_count": occt_view_count,
        "fallback": {
            "events_total": fallback_events_total,
            "timeout_events_total": timeout_events_total,
        },
    }
    if linework_counts_total is not None:
        summary_payload["linework_counts_total"] = linework_counts_total
    _write_json(
        run_dir / benchmark.RUNTIME_SUMMARY_RELATIVE,
        summary_payload,
    )
    if gate_status is not None:
        _write_json(run_dir / benchmark.RUNTIME_GATE_RELATIVE, {"status": gate_status})
    if runtime_s is not None:
        _write_json(run_dir / benchmark.PIPELINE_RUNTIME_RELATIVE, {"pipeline_runtime_s": runtime_s})
    return run_dir


def test_discover_and_load_sample_benchmark(tmp_path: Path):
    out_root = tmp_path / "bench"
    run_dir = _write_run(
        out_root,
        "sample_a",
        view_count=10,
        occt_view_count=8,
        fallback_events_total=2,
        timeout_events_total=1,
        linework_counts_total={"CUT": 3, "PROJECTED": 5, "HIDDEN": 2},
        gate_status="PASS",
        runtime_s=12.5,
    )

    dirs = benchmark.discover_run_dirs(out_root)
    assert dirs == [run_dir]

    item = benchmark.load_sample_benchmark(run_dir)
    assert item.sample == "sample_a"
    assert item.fallback_event_rate == 0.2
    assert item.occt_coverage_rate == 0.8
    assert item.linework_lines_total == 10
    assert item.hidden_lines_total == 2
    assert item.hidden_line_ratio == 0.2
    assert item.gate_status == "PASS"
    assert item.pipeline_runtime_s == 12.5


def test_build_benchmark_summary_aggregates_counts(tmp_path: Path):
    out_root = tmp_path / "bench"
    run_a = _write_run(
        out_root,
        "sample_a",
        view_count=10,
        occt_view_count=8,
        fallback_events_total=2,
        timeout_events_total=1,
        linework_counts_total={"CUT": 5, "PROJECTED": 3, "HIDDEN": 2},
        gate_status="PASS",
        runtime_s=10.0,
    )
    run_b = _write_run(
        out_root,
        "sample_b",
        view_count=5,
        occt_view_count=1,
        fallback_events_total=3,
        timeout_events_total=2,
        linework_counts_total={"CUT": 2, "PROJECTED": 3},
        gate_status="FAIL",
        runtime_s=20.0,
    )
    samples = [benchmark.load_sample_benchmark(run_a), benchmark.load_sample_benchmark(run_b)]
    summary = benchmark.build_benchmark_summary(samples)

    assert summary["sample_count"] == 2
    assert summary["gate"]["pass_count"] == 1
    assert summary["gate"]["fail_count"] == 1
    assert summary["gate"]["fail_samples"] == ["sample_b"]
    assert summary["runtime_seconds"]["median"] == 15.0
    assert summary["fallback_event_rate"]["max"] == 0.6
    assert summary["occt_coverage_rate"]["min"] == 0.2
    assert summary["hidden_lines_total"]["max"] == 2.0
    assert summary["hidden_line_ratio"]["min"] == 0.0

    md = benchmark.format_benchmark_markdown(summary)
    assert "OCCT Benchmark Summary" in md
    assert "| hidden_line_ratio |" in md
    assert "| sample_a | PASS |" in md
    assert "| sample_b | FAIL |" in md
    assert "| sample_b | FAIL | 20 | 5 | 1 | 3 | 0.600000 | 0.200000 | 5 | 0 | 0 |" in md


def test_benchmark_cli_strict_gate_returns_nonzero_on_fail(tmp_path: Path):
    out_root = tmp_path / "bench"
    _write_run(
        out_root,
        "sample_a",
        view_count=3,
        occt_view_count=0,
        fallback_events_total=1,
        timeout_events_total=1,
        gate_status="FAIL",
        runtime_s=7.0,
    )
    exit_code = benchmark.main([str(out_root), "--strict-gate"])
    assert exit_code == 1
    assert (out_root / "benchmark_summary.json").exists()
    assert (out_root / "benchmark_summary.md").exists()

    payload = json.loads((out_root / "benchmark_summary.json").read_text(encoding="utf-8"))
    assert payload["samples"][0]["linework_lines_total"] == 0
    assert payload["samples"][0]["hidden_lines_total"] == 0
    assert payload["samples"][0]["hidden_line_ratio"] == 0.0
