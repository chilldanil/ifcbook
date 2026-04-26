from __future__ import annotations

import json
from pathlib import Path

import pytest

from ifc_book_prototype import cli
from ifc_book_prototype.runtime_gate import (
    RuntimeGateThresholds,
    evaluate_runtime_gate,
    evaluate_runtime_gate_from_run_dir,
    format_runtime_gate_machine,
)


def _write_summary(run_dir: Path, payload: dict) -> Path:
    summary_path = run_dir / "metadata" / "geometry_runtime_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload), encoding="utf-8")
    return summary_path


def test_evaluate_runtime_gate_passes_all_thresholds():
    result = evaluate_runtime_gate(
        {
            "view_count": 10,
            "occt_view_count": 8,
            "linework_counts_total": {"CUT": 3, "PROJECTED": 5, "HIDDEN": 2},
            "fallback": {
                "events_total": 1,
                "timeout_events_total": 0,
            },
        },
        thresholds=RuntimeGateThresholds(
            max_fallback_event_rate=0.2,
            max_timeout_events_total=0,
            min_occt_coverage_rate=0.5,
        ),
        run_dir=Path("/tmp/run"),
        summary_path=Path("/tmp/run/metadata/geometry_runtime_summary.json"),
    )

    assert result.passed is True
    assert result.fallback_event_rate == pytest.approx(0.1)
    assert result.occt_coverage_rate == pytest.approx(0.8)
    assert result.hidden_lines_total == 2
    assert result.hidden_line_ratio == pytest.approx(0.2)
    assert [check.passed for check in result.checks] == [True, True, True]

    payload = json.loads(format_runtime_gate_machine(result))
    assert payload["status"] == "PASS"
    assert payload["metrics"]["fallback_events_total"] == 1


def test_evaluate_runtime_gate_hidden_thresholds_are_optional_and_back_compat():
    result = evaluate_runtime_gate(
        {
            "view_count": 10,
            "occt_view_count": 10,
            "fallback": {
                "events_total": 0,
                "timeout_events_total": 0,
            },
        },
        thresholds=RuntimeGateThresholds(min_occt_coverage_rate=1.0),
        run_dir=Path("/tmp/run"),
        summary_path=Path("/tmp/run/metadata/geometry_runtime_summary.json"),
    )

    assert result.passed is True
    assert result.linework_lines_total == 0
    assert result.hidden_lines_total == 0
    assert result.hidden_line_ratio == 0.0


def test_evaluate_runtime_gate_hidden_thresholds_fail_on_low_hidden_volume():
    result = evaluate_runtime_gate(
        {
            "view_count": 6,
            "occt_view_count": 6,
            "linework_counts_total": {"CUT": 4, "PROJECTED": 1, "HIDDEN": 1},
            "fallback": {
                "events_total": 0,
                "timeout_events_total": 0,
            },
        },
        thresholds=RuntimeGateThresholds(
            min_hidden_lines_total=2,
            min_hidden_line_ratio=0.25,
        ),
        run_dir=Path("/tmp/run"),
        summary_path=Path("/tmp/run/metadata/geometry_runtime_summary.json"),
    )

    assert result.passed is False
    assert result.hidden_lines_total == 1
    assert result.hidden_line_ratio == pytest.approx(1 / 6)
    assert [check.name for check in result.checks] == [
        "min_hidden_lines_total",
        "min_hidden_line_ratio",
    ]
    assert [check.passed for check in result.checks] == [False, False]


def test_evaluate_runtime_gate_fails_and_supports_legacy_timeout_key():
    result = evaluate_runtime_gate(
        {
            "view_count": 10,
            "occt_view_count": 3,
            "fallback": {
                "events_total": 9,
                "timeout_events": 2,
            },
        },
        thresholds=RuntimeGateThresholds(
            max_fallback_event_rate=0.5,
            max_timeout_events_total=1,
            min_occt_coverage_rate=0.4,
        ),
        run_dir=Path("/tmp/run"),
        summary_path=Path("/tmp/run/metadata/geometry_runtime_summary.json"),
    )

    assert result.passed is False
    assert result.timeout_events_total == 2
    assert [check.name for check in result.checks] == [
        "max_fallback_event_rate",
        "max_timeout_events_total",
        "min_occt_coverage_rate",
    ]
    assert [check.passed for check in result.checks] == [False, False, False]
    assert len(result.as_dict()["reasons"]) == 3


def test_evaluate_runtime_gate_from_run_dir_missing_summary(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="geometry_runtime_summary.json"):
        evaluate_runtime_gate_from_run_dir(
            tmp_path / "missing",
            thresholds=RuntimeGateThresholds(max_timeout_events_total=0),
        )


def test_cli_runtime_gate_pass_and_machine_output(tmp_path: Path, capsys):
    run_dir = tmp_path / "run"
    _write_summary(
        run_dir,
        {
            "view_count": 4,
            "occt_view_count": 2,
            "linework_counts_total": {"CUT": 2, "PROJECTED": 1, "HIDDEN": 1},
            "fallback": {
                "events_total": 1,
                "timeout_events_total": 0,
            },
        },
    )

    exit_code = cli.main(
        [
            "--runtime-gate",
            str(run_dir),
            "--max-fallback-event-rate",
            "0.3",
            "--max-timeout-events-total",
            "0",
            "--min-occt-coverage-rate",
            "0.5",
            "--min-hidden-lines-total",
            "1",
            "--min-hidden-line-ratio",
            "0.2",
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "RUNTIME_GATE PASS" in out
    machine_line = [line for line in out.splitlines() if line.startswith("RUNTIME_GATE_JSON=")][0]
    payload = json.loads(machine_line.split("=", 1)[1])
    assert payload["status"] == "PASS"
    assert payload["metrics"]["view_count"] == 4
    assert payload["metrics"]["hidden_lines_total"] == 1


def test_cli_runtime_gate_violation_returns_nonzero(tmp_path: Path, capsys):
    run_dir = tmp_path / "run"
    _write_summary(
        run_dir,
        {
            "view_count": 5,
            "occt_view_count": 1,
            "fallback": {
                "events_total": 3,
                "timeout_events_total": 2,
            },
        },
    )

    exit_code = cli.main(
        [
            "--runtime-gate",
            str(run_dir),
            "--max-fallback-event-rate",
            "0.4",
            "--max-timeout-events-total",
            "1",
            "--min-occt-coverage-rate",
            "0.3",
        ]
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "RUNTIME_GATE FAIL" in out


def test_cli_runtime_gate_requires_threshold(tmp_path: Path):
    run_dir = tmp_path / "run"
    _write_summary(
        run_dir,
        {
            "view_count": 1,
            "occt_view_count": 1,
            "fallback": {"events_total": 0, "timeout_events_total": 0},
        },
    )

    with pytest.raises(SystemExit) as exc:
        cli.main(["--runtime-gate", str(run_dir)])

    assert exc.value.code == 2


def test_cli_runtime_gate_missing_summary_returns_2(tmp_path: Path, capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    exit_code = cli.main(
        [
            "--runtime-gate",
            str(run_dir),
            "--max-timeout-events-total",
            "0",
        ]
    )

    assert exit_code == 2
    out = capsys.readouterr().out
    assert "ERROR:" in out


def test_cli_runtime_gate_invalid_threshold_returns_2(tmp_path: Path, capsys):
    run_dir = tmp_path / "run"
    _write_summary(
        run_dir,
        {
            "view_count": 2,
            "occt_view_count": 1,
            "fallback": {"events_total": 0, "timeout_events_total": 0},
        },
    )

    exit_code = cli.main(
        [
            "--runtime-gate",
            str(run_dir),
            "--min-occt-coverage-rate",
            "1.1",
        ]
    )

    assert exit_code == 2
    out = capsys.readouterr().out
    assert "ERROR:" in out
