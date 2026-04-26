from __future__ import annotations

import json
from pathlib import Path

import pytest

from ifc_book_prototype import cli
from ifc_book_prototype import progress_plan


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_run(
    run_root: Path,
    sample: str,
    *,
    view_count: int,
    occt_view_count: int,
    fallback_events_total: int,
    timeout_events_total: int,
    linework_counts_total: dict[str, int] | None = None,
    gate_status: str | None = None,
) -> Path:
    run_dir = run_root / sample
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
    _write_json(run_dir / progress_plan.RUNTIME_SUMMARY_RELATIVE, summary_payload)
    if gate_status is not None:
        _write_json(run_dir / progress_plan.RUNTIME_GATE_RELATIVE, {"status": gate_status})
    return run_dir


def test_create_progress_plan_from_run_root_aggregates_and_recommendations(tmp_path: Path):
    run_root = tmp_path / "runs"
    _write_run(
        run_root,
        "sample_b",
        view_count=10,
        occt_view_count=4,
        fallback_events_total=4,
        timeout_events_total=1,
        linework_counts_total={"CUT": 6, "PROJECTED": 4, "HIDDEN": 0},
        gate_status="FAIL",
    )
    _write_run(
        run_root,
        "sample_a",
        view_count=10,
        occt_view_count=8,
        fallback_events_total=3,
        timeout_events_total=0,
        linework_counts_total={"CUT": 4, "PROJECTED": 5, "HIDDEN": 1},
        gate_status="PASS",
    )

    plan = progress_plan.create_progress_plan_from_run_root(run_root)

    assert [sample.sample for sample in plan.samples] == ["sample_a", "sample_b"]
    assert plan.sample_count == 2
    assert plan.gate_pass_count == 1
    assert plan.gate_fail_count == 1
    assert plan.gate_missing_count == 0
    assert plan.fallback_event_rate_median == pytest.approx(0.35)
    assert plan.occt_coverage_rate_median == pytest.approx(0.6)
    assert plan.hidden_line_ratio_median == pytest.approx(0.05)
    assert list(plan.recommendations) == [
        progress_plan.REC_FALLBACK_HARDENING,
        progress_plan.REC_OCCT_COVERAGE,
        progress_plan.REC_HIDDEN_EXTRACTION,
        progress_plan.REC_GATE_TIGHTENING,
        progress_plan.REC_SEMANTIC_ROADMAP,
    ]

    human = progress_plan.format_progress_plan_human(plan)
    assert "PROGRESS_PLAN run_root=" in human
    assert "median.fallback_event_rate=0.350000" in human
    assert "1. " in human

    markdown = progress_plan.format_progress_plan_markdown(plan)
    assert "# Progress Plan" in markdown
    assert "## Recommendations" in markdown
    assert "| sample_a | PASS |" in markdown
    assert "| sample_b | FAIL |" in markdown


def test_create_progress_plan_from_run_root_rejects_invalid_root(tmp_path: Path):
    missing_root = tmp_path / "missing"
    with pytest.raises(ValueError, match="Run root does not exist"):
        progress_plan.create_progress_plan_from_run_root(missing_root)

    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    with pytest.raises(ValueError, match="No run directories"):
        progress_plan.create_progress_plan_from_run_root(empty_root)


def test_cli_plan_next_prints_summary_and_writes_markdown(tmp_path: Path, capsys):
    run_root = tmp_path / "runs"
    _write_run(
        run_root,
        "sample_a",
        view_count=8,
        occt_view_count=4,
        fallback_events_total=2,
        timeout_events_total=0,
        linework_counts_total={"CUT": 4, "PROJECTED": 4, "HIDDEN": 0},
        gate_status="PASS",
    )
    report_path = tmp_path / "report" / "plan.md"
    json_path = tmp_path / "report" / "plan.json"
    svg_path = tmp_path / "report" / "plan.svg"

    exit_code = cli.main(
        [
            "--plan-next",
            str(run_root),
            "--plan-next-out",
            str(report_path),
            "--plan-next-json-out",
            str(json_path),
            "--plan-next-svg-out",
            str(svg_path),
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PROGRESS_PLAN run_root=" in out
    assert "recommendations:" in out
    assert "1. " in out
    assert f"plan_next_report={report_path}" in out
    assert f"plan_next_json={json_path}" in out
    assert f"plan_next_svg={svg_path}" in out
    assert report_path.exists()
    assert report_path.stat().st_size > 0
    assert json_path.exists()
    assert json_path.stat().st_size > 0
    assert svg_path.exists()
    assert svg_path.stat().st_size > 0
    markdown = report_path.read_text(encoding="utf-8")
    assert "## Recommendations" in markdown
    assert "## Per Sample" in markdown
    plan_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert plan_json["sample_count"] == 1
    assert isinstance(plan_json["recommendations"], list)
    svg = svg_path.read_text(encoding="utf-8")
    assert "Progress Plan Dashboard" in svg
    assert "sample_count: 1" in svg
    assert "Recommendations" in svg


def test_cli_plan_next_invalid_root_returns_2(tmp_path: Path, capsys):
    exit_code = cli.main(["--plan-next", str(tmp_path / "missing")])
    assert exit_code == 2
    out = capsys.readouterr().out
    assert "ERROR:" in out


def test_cli_plan_next_out_requires_plan_next(tmp_path: Path):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--plan-next-out", str(tmp_path / "plan.md")])
    assert exc.value.code == 2


def test_cli_plan_next_json_out_requires_plan_next(tmp_path: Path):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--plan-next-json-out", str(tmp_path / "plan.json")])
    assert exc.value.code == 2


def test_cli_plan_next_svg_out_requires_plan_next(tmp_path: Path):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--plan-next-svg-out", str(tmp_path / "plan.svg")])
    assert exc.value.code == 2


def test_format_progress_plan_svg_is_deterministic(tmp_path: Path):
    run_root = tmp_path / "runs"
    _write_run(
        run_root,
        "sample_b",
        view_count=10,
        occt_view_count=4,
        fallback_events_total=4,
        timeout_events_total=1,
        linework_counts_total={"CUT": 6, "PROJECTED": 4, "HIDDEN": 0},
        gate_status="FAIL",
    )
    _write_run(
        run_root,
        "sample_a",
        view_count=10,
        occt_view_count=8,
        fallback_events_total=3,
        timeout_events_total=0,
        linework_counts_total={"CUT": 4, "PROJECTED": 5, "HIDDEN": 1},
        gate_status="PASS",
    )

    plan = progress_plan.create_progress_plan_from_run_root(run_root)

    svg_a = progress_plan.format_progress_plan_svg(plan)
    svg_b = progress_plan.format_progress_plan_svg(plan)

    assert svg_a == svg_b
    assert "<svg " in svg_a
    assert "sample_count: 2" in svg_a
    assert "median.fallback_event_rate: 0.350000" in svg_a
    assert "median.occt_coverage_rate: 0.600000" in svg_a
    assert "Recommendations" in svg_a
    assert f"1. {progress_plan.REC_FALLBACK_HARDENING}" in svg_a
