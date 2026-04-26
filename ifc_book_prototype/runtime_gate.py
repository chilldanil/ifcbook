from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SUMMARY_RELATIVE_PATH = Path("metadata") / "geometry_runtime_summary.json"


@dataclass(frozen=True)
class RuntimeGateThresholds:
    max_fallback_event_rate: float | None = None
    max_timeout_events_total: int | None = None
    min_occt_coverage_rate: float | None = None
    min_hidden_lines_total: int | None = None
    min_hidden_line_ratio: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_fallback_event_rate": self.max_fallback_event_rate,
            "max_timeout_events_total": self.max_timeout_events_total,
            "min_occt_coverage_rate": self.min_occt_coverage_rate,
            "min_hidden_lines_total": self.min_hidden_lines_total,
            "min_hidden_line_ratio": self.min_hidden_line_ratio,
        }

    def has_any_limit(self) -> bool:
        return any(value is not None for value in self.as_dict().values())

    def validate(self) -> None:
        if self.max_fallback_event_rate is not None and self.max_fallback_event_rate < 0:
            raise ValueError("Threshold 'max_fallback_event_rate' must be >= 0.")
        if self.max_timeout_events_total is not None and self.max_timeout_events_total < 0:
            raise ValueError("Threshold 'max_timeout_events_total' must be >= 0.")
        if self.min_occt_coverage_rate is not None:
            if self.min_occt_coverage_rate < 0 or self.min_occt_coverage_rate > 1:
                raise ValueError("Threshold 'min_occt_coverage_rate' must be between 0 and 1.")
        if self.min_hidden_lines_total is not None and self.min_hidden_lines_total < 0:
            raise ValueError("Threshold 'min_hidden_lines_total' must be >= 0.")
        if self.min_hidden_line_ratio is not None:
            if self.min_hidden_line_ratio < 0 or self.min_hidden_line_ratio > 1:
                raise ValueError("Threshold 'min_hidden_line_ratio' must be between 0 and 1.")


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    actual: float
    threshold: float
    comparator: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": "PASS" if self.passed else "FAIL",
            "passed": self.passed,
            "actual": self.actual,
            "threshold": self.threshold,
            "comparator": self.comparator,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeGateResult:
    run_dir: Path
    summary_path: Path
    thresholds: RuntimeGateThresholds
    view_count: int
    occt_view_count: int
    linework_lines_total: int
    hidden_lines_total: int
    fallback_events_total: int
    timeout_events_total: int
    fallback_event_rate: float
    occt_coverage_rate: float
    hidden_line_ratio: float
    checks: tuple[GateCheck, ...]
    passed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "PASS" if self.passed else "FAIL",
            "passed": self.passed,
            "run_dir": str(self.run_dir),
            "summary_path": str(self.summary_path),
            "metrics": {
                "view_count": self.view_count,
                "occt_view_count": self.occt_view_count,
                "linework_lines_total": self.linework_lines_total,
                "hidden_lines_total": self.hidden_lines_total,
                "fallback_events_total": self.fallback_events_total,
                "timeout_events_total": self.timeout_events_total,
                "fallback_event_rate": self.fallback_event_rate,
                "occt_coverage_rate": self.occt_coverage_rate,
                "hidden_line_ratio": self.hidden_line_ratio,
            },
            "thresholds": self.thresholds.as_dict(),
            "checks": [check.as_dict() for check in self.checks],
            "reasons": [check.reason for check in self.checks if not check.passed],
        }


def evaluate_runtime_gate_from_run_dir(
    run_dir: Path,
    *,
    thresholds: RuntimeGateThresholds,
) -> RuntimeGateResult:
    summary_path = run_dir / SUMMARY_RELATIVE_PATH
    data = _load_runtime_summary(summary_path)
    return evaluate_runtime_gate(
        data,
        thresholds=thresholds,
        run_dir=run_dir,
        summary_path=summary_path,
    )


def evaluate_runtime_gate(
    summary_data: Mapping[str, Any],
    *,
    thresholds: RuntimeGateThresholds,
    run_dir: Path,
    summary_path: Path,
) -> RuntimeGateResult:
    thresholds.validate()
    view_count = _as_int(summary_data.get("view_count", 0), "view_count")
    occt_view_count = _as_int(summary_data.get("occt_view_count", 0), "occt_view_count")
    fallback = summary_data.get("fallback", {})
    if not isinstance(fallback, Mapping):
        raise ValueError("Field 'fallback' must be an object.")

    fallback_events_total = _as_int(fallback.get("events_total", 0), "fallback.events_total")
    timeout_events_total = _as_int(
        fallback.get("timeout_events_total", fallback.get("timeout_events", 0)),
        "fallback.timeout_events_total",
    )
    hidden_lines_total, linework_lines_total = _extract_hidden_metrics(
        summary_data.get("linework_counts_total", {})
    )

    fallback_event_rate = _safe_rate(fallback_events_total, view_count)
    occt_coverage_rate = _safe_rate(occt_view_count, view_count)
    hidden_line_ratio = _safe_rate(hidden_lines_total, linework_lines_total)

    checks: list[GateCheck] = []
    if thresholds.max_fallback_event_rate is not None:
        checks.append(
            _build_check(
                name="max_fallback_event_rate",
                actual=fallback_event_rate,
                threshold=float(thresholds.max_fallback_event_rate),
                comparator="<=",
            )
        )
    if thresholds.max_timeout_events_total is not None:
        checks.append(
            _build_check(
                name="max_timeout_events_total",
                actual=float(timeout_events_total),
                threshold=float(thresholds.max_timeout_events_total),
                comparator="<=",
            )
        )
    if thresholds.min_occt_coverage_rate is not None:
        checks.append(
            _build_check(
                name="min_occt_coverage_rate",
                actual=occt_coverage_rate,
                threshold=float(thresholds.min_occt_coverage_rate),
                comparator=">=",
            )
        )
    if thresholds.min_hidden_lines_total is not None:
        checks.append(
            _build_check(
                name="min_hidden_lines_total",
                actual=float(hidden_lines_total),
                threshold=float(thresholds.min_hidden_lines_total),
                comparator=">=",
            )
        )
    if thresholds.min_hidden_line_ratio is not None:
        checks.append(
            _build_check(
                name="min_hidden_line_ratio",
                actual=hidden_line_ratio,
                threshold=float(thresholds.min_hidden_line_ratio),
                comparator=">=",
            )
        )

    passed = all(check.passed for check in checks)
    return RuntimeGateResult(
        run_dir=run_dir,
        summary_path=summary_path,
        thresholds=thresholds,
        view_count=view_count,
        occt_view_count=occt_view_count,
        linework_lines_total=linework_lines_total,
        hidden_lines_total=hidden_lines_total,
        fallback_events_total=fallback_events_total,
        timeout_events_total=timeout_events_total,
        fallback_event_rate=fallback_event_rate,
        occt_coverage_rate=occt_coverage_rate,
        hidden_line_ratio=hidden_line_ratio,
        checks=tuple(checks),
        passed=passed,
    )


def format_runtime_gate_human(result: RuntimeGateResult) -> str:
    lines = [
        f"RUNTIME_GATE {'PASS' if result.passed else 'FAIL'} run_dir={result.run_dir}",
        (
            "metrics: "
            f"view_count={result.view_count} "
            f"occt_view_count={result.occt_view_count} "
            f"linework_lines_total={result.linework_lines_total} "
            f"hidden_lines_total={result.hidden_lines_total} "
            f"fallback_events_total={result.fallback_events_total} "
            f"timeout_events_total={result.timeout_events_total} "
            f"fallback_event_rate={result.fallback_event_rate:.6f} "
            f"occt_coverage_rate={result.occt_coverage_rate:.6f} "
            f"hidden_line_ratio={result.hidden_line_ratio:.6f}"
        ),
    ]
    if result.checks:
        lines.append("checks:")
        for check in result.checks:
            lines.append(
                f"  {'PASS' if check.passed else 'FAIL'} {check.name}: {check.reason}"
            )
    else:
        lines.append("checks: (none)")
    return "\n".join(lines)


def format_runtime_gate_machine(result: RuntimeGateResult) -> str:
    return json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":"))


def _load_runtime_summary(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return data


def _extract_hidden_metrics(linework_counts: Any) -> tuple[int, int]:
    if linework_counts is None:
        return 0, 0
    if not isinstance(linework_counts, Mapping):
        raise ValueError("Field 'linework_counts_total' must be an object.")

    hidden_lines_total = 0
    linework_lines_total = 0
    for kind, raw_value in linework_counts.items():
        count = _as_int(raw_value, f"linework_counts_total.{kind}")
        linework_lines_total += count
        if str(kind).strip().upper() == "HIDDEN":
            hidden_lines_total += count
    return hidden_lines_total, linework_lines_total


def _build_check(*, name: str, actual: float, threshold: float, comparator: str) -> GateCheck:
    if comparator == "<=":
        passed = actual <= threshold
    elif comparator == ">=":
        passed = actual >= threshold
    else:
        raise ValueError(f"Unsupported comparator: {comparator}")

    reason = (
        f"{name}: actual={_format_number(actual)} "
        f"{comparator} threshold={_format_number(threshold)}"
    )
    return GateCheck(
        name=name,
        passed=passed,
        actual=actual,
        threshold=threshold,
        comparator=comparator,
        reason=reason,
    )


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.6f}"


def _as_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Field '{field_name}' must be an integer-compatible value.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"Field '{field_name}' must be an integer-compatible value.")
        parsed = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        try:
            parsed = int(stripped, 10)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Field '{field_name}' must be an integer-compatible value.") from exc
    else:
        raise ValueError(f"Field '{field_name}' must be an integer-compatible value.")
    if parsed < 0:
        raise ValueError(f"Field '{field_name}' must be >= 0.")
    return parsed


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)
