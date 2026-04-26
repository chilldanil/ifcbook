from __future__ import annotations

from html import escape
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


RUNTIME_SUMMARY_RELATIVE = Path("metadata") / "geometry_runtime_summary.json"
RUNTIME_GATE_RELATIVE = Path("metadata") / "runtime_gate_result.json"

HIGH_FALLBACK_EVENT_RATE_THRESHOLD = 0.20
LOW_OCCT_COVERAGE_RATE_THRESHOLD = 0.70
LOW_HIDDEN_LINE_RATIO_THRESHOLD = 0.08

REC_FALLBACK_HARDENING = (
    "Harden fallback paths: prioritize timeout/empty-case handling to reduce "
    "fallback_event_rate below 0.20 median."
)
REC_OCCT_COVERAGE = (
    "Increase OCCT coverage: expand owned-projection eligibility and class handling "
    "to raise occt_coverage_rate above 0.70 median."
)
REC_HIDDEN_EXTRACTION = (
    "Tune hidden extraction: improve HLR hidden-compound collection, sampling, and "
    "dedupe to raise hidden_line_ratio above 0.08 median."
)
REC_GATE_TIGHTENING = (
    "Tighten CI/runtime gates: enforce runtime_gate_result FAIL as a blocking signal "
    "and keep per-sample thresholds explicit."
)
REC_SEMANTIC_ROADMAP = (
    "Forward roadmap: implement next semantic drafting upgrades (door swings, stair "
    "arrows, room annotations) on top of stabilized geometry metrics."
)


@dataclass(frozen=True)
class ProgressSample:
    sample: str
    run_dir: Path
    view_count: int
    occt_view_count: int
    linework_lines_total: int
    hidden_lines_total: int
    fallback_events_total: int
    timeout_events_total: int
    fallback_event_rate: float
    occt_coverage_rate: float
    hidden_line_ratio: float
    gate_status: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample": self.sample,
            "run_dir": str(self.run_dir),
            "view_count": self.view_count,
            "occt_view_count": self.occt_view_count,
            "linework_lines_total": self.linework_lines_total,
            "hidden_lines_total": self.hidden_lines_total,
            "fallback_events_total": self.fallback_events_total,
            "timeout_events_total": self.timeout_events_total,
            "fallback_event_rate": self.fallback_event_rate,
            "occt_coverage_rate": self.occt_coverage_rate,
            "hidden_line_ratio": self.hidden_line_ratio,
            "gate_status": self.gate_status,
        }


@dataclass(frozen=True)
class ProgressPlan:
    run_root: Path
    sample_count: int
    gate_pass_count: int
    gate_fail_count: int
    gate_missing_count: int
    fallback_event_rate_median: float
    occt_coverage_rate_median: float
    hidden_line_ratio_median: float
    recommendations: tuple[str, ...]
    samples: tuple[ProgressSample, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_root": str(self.run_root),
            "sample_count": self.sample_count,
            "gate": {
                "pass_count": self.gate_pass_count,
                "fail_count": self.gate_fail_count,
                "missing_count": self.gate_missing_count,
            },
            "medians": {
                "fallback_event_rate": self.fallback_event_rate_median,
                "occt_coverage_rate": self.occt_coverage_rate_median,
                "hidden_line_ratio": self.hidden_line_ratio_median,
            },
            "recommendations": list(self.recommendations),
            "samples": [sample.as_dict() for sample in self.samples],
        }


def create_progress_plan_from_run_root(run_root: Path) -> ProgressPlan:
    run_dirs = discover_run_dirs(run_root)
    samples = [load_progress_sample(run_dir) for run_dir in run_dirs]
    return build_progress_plan(samples, run_root=run_root)


def discover_run_dirs(run_root: Path) -> list[Path]:
    if not run_root.exists():
        raise ValueError(f"Run root does not exist: {run_root}")
    if not run_root.is_dir():
        raise ValueError(f"Run root is not a directory: {run_root}")

    run_dirs: list[Path] = []
    for child in sorted(run_root.iterdir()):
        if not child.is_dir():
            continue
        if (child / RUNTIME_SUMMARY_RELATIVE).exists():
            run_dirs.append(child)
    if not run_dirs:
        raise ValueError(
            f"No run directories with {RUNTIME_SUMMARY_RELATIVE} under {run_root}."
        )
    return run_dirs


def load_progress_sample(run_dir: Path) -> ProgressSample:
    summary_path = run_dir / RUNTIME_SUMMARY_RELATIVE
    summary = _load_json_object(summary_path)
    fallback = summary.get("fallback", {})
    if not isinstance(fallback, Mapping):
        raise ValueError(f"Invalid fallback object in {summary_path}.")

    view_count = _as_int(summary.get("view_count", 0), "view_count")
    occt_view_count = _as_int(summary.get("occt_view_count", 0), "occt_view_count")
    fallback_events_total = _as_int(fallback.get("events_total", 0), "fallback.events_total")
    timeout_events_total = _as_int(
        fallback.get("timeout_events_total", fallback.get("timeout_events", 0)),
        "fallback.timeout_events_total",
    )
    hidden_lines_total, linework_lines_total = _extract_hidden_metrics(
        summary.get("linework_counts_total", {})
    )
    gate_status = _load_gate_status(run_dir / RUNTIME_GATE_RELATIVE)

    return ProgressSample(
        sample=run_dir.name,
        run_dir=run_dir,
        view_count=view_count,
        occt_view_count=occt_view_count,
        linework_lines_total=linework_lines_total,
        hidden_lines_total=hidden_lines_total,
        fallback_events_total=fallback_events_total,
        timeout_events_total=timeout_events_total,
        fallback_event_rate=_safe_rate(fallback_events_total, view_count),
        occt_coverage_rate=_safe_rate(occt_view_count, view_count),
        hidden_line_ratio=_safe_rate(hidden_lines_total, linework_lines_total),
        gate_status=gate_status,
    )


def build_progress_plan(samples: Iterable[ProgressSample], *, run_root: Path) -> ProgressPlan:
    sample_list = sorted(samples, key=lambda item: item.sample)
    if not sample_list:
        raise ValueError("At least one sample with runtime summary is required.")

    fallback_median = _median([item.fallback_event_rate for item in sample_list])
    coverage_median = _median([item.occt_coverage_rate for item in sample_list])
    hidden_ratio_median = _median([item.hidden_line_ratio for item in sample_list])
    gate_pass_count = sum(1 for item in sample_list if item.gate_status == "PASS")
    gate_fail_count = sum(1 for item in sample_list if item.gate_status == "FAIL")
    gate_missing_count = sum(1 for item in sample_list if item.gate_status is None)

    recommendations = _build_recommendations(
        fallback_event_rate_median=fallback_median,
        occt_coverage_rate_median=coverage_median,
        hidden_line_ratio_median=hidden_ratio_median,
        gate_fail_count=gate_fail_count,
    )
    return ProgressPlan(
        run_root=run_root,
        sample_count=len(sample_list),
        gate_pass_count=gate_pass_count,
        gate_fail_count=gate_fail_count,
        gate_missing_count=gate_missing_count,
        fallback_event_rate_median=fallback_median,
        occt_coverage_rate_median=coverage_median,
        hidden_line_ratio_median=hidden_ratio_median,
        recommendations=tuple(recommendations),
        samples=tuple(sample_list),
    )


def format_progress_plan_human(plan: ProgressPlan) -> str:
    lines = [
        f"PROGRESS_PLAN run_root={plan.run_root}",
        (
            "samples="
            f"{plan.sample_count} gate_pass={plan.gate_pass_count} "
            f"gate_fail={plan.gate_fail_count} gate_missing={plan.gate_missing_count}"
        ),
        f"median.fallback_event_rate={plan.fallback_event_rate_median:.6f}",
        f"median.occt_coverage_rate={plan.occt_coverage_rate_median:.6f}",
        f"median.hidden_line_ratio={plan.hidden_line_ratio_median:.6f}",
        "recommendations:",
    ]
    for index, recommendation in enumerate(plan.recommendations, start=1):
        lines.append(f"{index}. {recommendation}")
    return "\n".join(lines)


def format_progress_plan_markdown(plan: ProgressPlan) -> str:
    lines = [
        "# Progress Plan",
        "",
        f"- run_root: {plan.run_root}",
        f"- sample_count: {plan.sample_count}",
        f"- gate_pass_count: {plan.gate_pass_count}",
        f"- gate_fail_count: {plan.gate_fail_count}",
        f"- gate_missing_count: {plan.gate_missing_count}",
        f"- median_fallback_event_rate: {plan.fallback_event_rate_median:.6f}",
        f"- median_occt_coverage_rate: {plan.occt_coverage_rate_median:.6f}",
        f"- median_hidden_line_ratio: {plan.hidden_line_ratio_median:.6f}",
        "",
        "## Recommendations",
        "",
    ]
    for index, recommendation in enumerate(plan.recommendations, start=1):
        lines.append(f"{index}. {recommendation}")

    lines.extend(
        [
            "",
            "## Per Sample",
            "",
            "| sample | gate | fallback_event_rate | occt_coverage_rate | hidden_line_ratio |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for sample in plan.samples:
        lines.append(
            "| "
            + sample.sample
            + " | "
            + str(sample.gate_status or "-")
            + " | "
            + f"{sample.fallback_event_rate:.6f}"
            + " | "
            + f"{sample.occt_coverage_rate:.6f}"
            + " | "
            + f"{sample.hidden_line_ratio:.6f}"
            + " |"
        )
    return "\n".join(lines) + "\n"


def format_progress_plan_svg(plan: ProgressPlan) -> str:
    summary_lines = [
        f"run_root: {plan.run_root}",
        f"sample_count: {plan.sample_count}",
        f"gate_pass_count: {plan.gate_pass_count}",
        f"gate_fail_count: {plan.gate_fail_count}",
        f"gate_missing_count: {plan.gate_missing_count}",
        f"median.fallback_event_rate: {plan.fallback_event_rate_median:.6f}",
        f"median.occt_coverage_rate: {plan.occt_coverage_rate_median:.6f}",
        f"median.hidden_line_ratio: {plan.hidden_line_ratio_median:.6f}",
    ]
    recommendation_lines = [
        f"{index}. {recommendation}"
        for index, recommendation in enumerate(plan.recommendations, start=1)
    ]

    width = 1100
    line_height = 24
    margin_x = 40
    y_start = 56
    text_line_count = 2 + len(summary_lines) + len(recommendation_lines)
    height = max(220, y_start + text_line_count * line_height + 36)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="Progress plan dashboard">'
        ),
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#f8fafc" />',
        (
            f'<rect x="16" y="16" width="{width - 32}" height="{height - 32}" '
            'fill="#ffffff" stroke="#d1d5db" stroke-width="1" rx="10" ry="10" />'
        ),
        (
            f'<text x="{margin_x}" y="{y_start}" font-family="monospace" '
            'font-size="26" font-weight="700" fill="#111827">Progress Plan Dashboard</text>'
        ),
    ]

    y = y_start + line_height
    for line in summary_lines:
        lines.append(
            f'<text x="{margin_x}" y="{y}" font-family="monospace" '
            f'font-size="16" fill="#1f2937">{escape(line)}</text>'
        )
        y += line_height

    lines.append(
        f'<text x="{margin_x}" y="{y}" font-family="monospace" '
        'font-size="18" font-weight="600" fill="#111827">Recommendations</text>'
    )
    y += line_height

    for line in recommendation_lines:
        lines.append(
            f'<text x="{margin_x}" y="{y}" font-family="monospace" '
            f'font-size="16" fill="#1f2937">{escape(line)}</text>'
        )
        y += line_height

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _build_recommendations(
    *,
    fallback_event_rate_median: float,
    occt_coverage_rate_median: float,
    hidden_line_ratio_median: float,
    gate_fail_count: int,
) -> list[str]:
    recommendations: list[str] = []
    if fallback_event_rate_median >= HIGH_FALLBACK_EVENT_RATE_THRESHOLD:
        recommendations.append(REC_FALLBACK_HARDENING)
    if occt_coverage_rate_median < LOW_OCCT_COVERAGE_RATE_THRESHOLD:
        recommendations.append(REC_OCCT_COVERAGE)
    if hidden_line_ratio_median < LOW_HIDDEN_LINE_RATIO_THRESHOLD:
        recommendations.append(REC_HIDDEN_EXTRACTION)
    if gate_fail_count > 0:
        recommendations.append(REC_GATE_TIGHTENING)
    recommendations.append(REC_SEMANTIC_ROADMAP)
    return recommendations


def _load_gate_status(path: Path) -> str | None:
    if not path.exists():
        return None
    payload = _load_json_object(path)
    status = str(payload.get("status", "")).strip().upper()
    if status in {"PASS", "FAIL"}:
        return status
    return None


def _load_json_object(path: Path) -> Mapping[str, Any]:
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


def _as_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Field '{field_name}' must be integer-compatible.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"Field '{field_name}' must be integer-compatible.")
        parsed = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        try:
            parsed = int(stripped, 10)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Field '{field_name}' must be integer-compatible.") from exc
    else:
        raise ValueError(f"Field '{field_name}' must be integer-compatible.")
    if parsed < 0:
        raise ValueError(f"Field '{field_name}' must be >= 0.")
    return parsed


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))
