from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Mapping


RUNTIME_SUMMARY_RELATIVE = Path("metadata") / "geometry_runtime_summary.json"
RUNTIME_GATE_RELATIVE = Path("metadata") / "runtime_gate_result.json"
PIPELINE_RUNTIME_RELATIVE = Path("metadata") / "benchmark_runtime.json"


@dataclass(frozen=True)
class SampleBenchmark:
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
    pipeline_runtime_s: float | None
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
            "pipeline_runtime_s": self.pipeline_runtime_s,
            "gate_status": self.gate_status,
        }


def discover_run_dirs(out_root: Path) -> List[Path]:
    if not out_root.exists():
        return []
    run_dirs: List[Path] = []
    for child in sorted(out_root.iterdir()):
        if not child.is_dir():
            continue
        if (child / RUNTIME_SUMMARY_RELATIVE).exists():
            run_dirs.append(child)
    return run_dirs


def load_sample_benchmark(run_dir: Path) -> SampleBenchmark:
    summary = _load_json_object(run_dir / RUNTIME_SUMMARY_RELATIVE)
    fallback = summary.get("fallback", {})
    if not isinstance(fallback, Mapping):
        raise ValueError(f"Invalid fallback object in {run_dir / RUNTIME_SUMMARY_RELATIVE}.")

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
    fallback_event_rate = _safe_rate(fallback_events_total, view_count)
    occt_coverage_rate = _safe_rate(occt_view_count, view_count)
    hidden_line_ratio = _safe_rate(hidden_lines_total, linework_lines_total)

    pipeline_runtime_s = None
    runtime_path = run_dir / PIPELINE_RUNTIME_RELATIVE
    if runtime_path.exists():
        runtime_payload = _load_json_object(runtime_path)
        pipeline_runtime_s = _as_non_negative_float(
            runtime_payload.get("pipeline_runtime_s", 0.0),
            "pipeline_runtime_s",
        )

    gate_status = None
    gate_path = run_dir / RUNTIME_GATE_RELATIVE
    if gate_path.exists():
        gate_payload = _load_json_object(gate_path)
        raw_status = str(gate_payload.get("status", "")).strip().upper()
        if raw_status in {"PASS", "FAIL"}:
            gate_status = raw_status

    return SampleBenchmark(
        sample=run_dir.name,
        run_dir=run_dir,
        view_count=view_count,
        occt_view_count=occt_view_count,
        linework_lines_total=linework_lines_total,
        hidden_lines_total=hidden_lines_total,
        fallback_events_total=fallback_events_total,
        timeout_events_total=timeout_events_total,
        fallback_event_rate=fallback_event_rate,
        occt_coverage_rate=occt_coverage_rate,
        hidden_line_ratio=hidden_line_ratio,
        pipeline_runtime_s=pipeline_runtime_s,
        gate_status=gate_status,
    )


def build_benchmark_summary(samples: Iterable[SampleBenchmark]) -> dict[str, Any]:
    sample_list = sorted(samples, key=lambda item: item.sample)
    runtime_values = [item.pipeline_runtime_s for item in sample_list if item.pipeline_runtime_s is not None]
    fallback_rates = [item.fallback_event_rate for item in sample_list]
    coverage_rates = [item.occt_coverage_rate for item in sample_list]
    hidden_totals = [float(item.hidden_lines_total) for item in sample_list]
    hidden_ratios = [item.hidden_line_ratio for item in sample_list]

    gate_pass_count = sum(1 for item in sample_list if item.gate_status == "PASS")
    gate_fail_count = sum(1 for item in sample_list if item.gate_status == "FAIL")
    gate_missing_count = sum(1 for item in sample_list if item.gate_status is None)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(sample_list),
        "gate": {
            "pass_count": gate_pass_count,
            "fail_count": gate_fail_count,
            "missing_count": gate_missing_count,
            "fail_samples": [item.sample for item in sample_list if item.gate_status == "FAIL"],
        },
        "runtime_seconds": _summary_stats(runtime_values),
        "fallback_event_rate": _summary_stats(fallback_rates),
        "occt_coverage_rate": _summary_stats(coverage_rates),
        "hidden_lines_total": _summary_stats(hidden_totals),
        "hidden_line_ratio": _summary_stats(hidden_ratios),
        "samples": [item.as_dict() for item in sample_list],
    }


def format_benchmark_markdown(summary: Mapping[str, Any]) -> str:
    gate = summary.get("gate", {}) if isinstance(summary, Mapping) else {}
    runtime_stats = summary.get("runtime_seconds", {}) if isinstance(summary, Mapping) else {}
    fallback_stats = summary.get("fallback_event_rate", {}) if isinstance(summary, Mapping) else {}
    coverage_stats = summary.get("occt_coverage_rate", {}) if isinstance(summary, Mapping) else {}
    hidden_total_stats = summary.get("hidden_lines_total", {}) if isinstance(summary, Mapping) else {}
    hidden_ratio_stats = summary.get("hidden_line_ratio", {}) if isinstance(summary, Mapping) else {}
    samples = summary.get("samples", []) if isinstance(summary, Mapping) else []

    lines = [
        "# OCCT Benchmark Summary",
        "",
        f"- generated_at_utc: {summary.get('generated_at_utc', '')}",
        f"- sample_count: {summary.get('sample_count', 0)}",
        f"- gate.pass_count: {gate.get('pass_count', 0)}",
        f"- gate.fail_count: {gate.get('fail_count', 0)}",
        f"- gate.missing_count: {gate.get('missing_count', 0)}",
        "",
        "## Aggregate Stats",
        "",
        "| metric | min | median | mean | max |",
        "|---|---:|---:|---:|---:|",
        "| runtime_seconds | "
        + _fmt(runtime_stats.get("min"))
        + " | "
        + _fmt(runtime_stats.get("median"))
        + " | "
        + _fmt(runtime_stats.get("mean"))
        + " | "
        + _fmt(runtime_stats.get("max"))
        + " |",
        "| fallback_event_rate | "
        + _fmt(fallback_stats.get("min"))
        + " | "
        + _fmt(fallback_stats.get("median"))
        + " | "
        + _fmt(fallback_stats.get("mean"))
        + " | "
        + _fmt(fallback_stats.get("max"))
        + " |",
        "| occt_coverage_rate | "
        + _fmt(coverage_stats.get("min"))
        + " | "
        + _fmt(coverage_stats.get("median"))
        + " | "
        + _fmt(coverage_stats.get("mean"))
        + " | "
        + _fmt(coverage_stats.get("max"))
        + " |",
        "| hidden_lines_total | "
        + _fmt(hidden_total_stats.get("min"))
        + " | "
        + _fmt(hidden_total_stats.get("median"))
        + " | "
        + _fmt(hidden_total_stats.get("mean"))
        + " | "
        + _fmt(hidden_total_stats.get("max"))
        + " |",
        "| hidden_line_ratio | "
        + _fmt(hidden_ratio_stats.get("min"))
        + " | "
        + _fmt(hidden_ratio_stats.get("median"))
        + " | "
        + _fmt(hidden_ratio_stats.get("mean"))
        + " | "
        + _fmt(hidden_ratio_stats.get("max"))
        + " |",
        "",
        "## Per Sample",
        "",
        "| sample | gate | runtime_s | view_count | occt_views | fallback_events | fallback_rate | occt_coverage | linework_lines | hidden_lines | hidden_ratio |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in samples:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            + str(item.get("sample", ""))
            + " | "
            + str(item.get("gate_status", ""))
            + " | "
            + _fmt(item.get("pipeline_runtime_s"))
            + " | "
            + str(item.get("view_count", ""))
            + " | "
            + str(item.get("occt_view_count", ""))
            + " | "
            + str(item.get("fallback_events_total", ""))
            + " | "
            + _fmt(item.get("fallback_event_rate"))
            + " | "
            + _fmt(item.get("occt_coverage_rate"))
            + " | "
            + str(item.get("linework_lines_total", ""))
            + " | "
            + str(item.get("hidden_lines_total", ""))
            + " | "
            + _fmt(item.get("hidden_line_ratio"))
            + " |"
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate OCCT benchmark run directories.")
    parser.add_argument("out_root", help="Root directory containing per-sample run directories.")
    parser.add_argument("--json-out", help="Output path for JSON summary.")
    parser.add_argument("--md-out", help="Output path for Markdown summary.")
    parser.add_argument(
        "--strict-gate",
        action="store_true",
        help="Return non-zero when at least one sample has gate_status=FAIL.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    out_root = Path(args.out_root)
    run_dirs = discover_run_dirs(out_root)
    if not run_dirs:
        print(f"ERROR: no run directories with {RUNTIME_SUMMARY_RELATIVE} under {out_root}")
        return 2

    samples = [load_sample_benchmark(run_dir) for run_dir in run_dirs]
    summary = build_benchmark_summary(samples)

    json_out = Path(args.json_out) if args.json_out else out_root / "benchmark_summary.json"
    md_out = Path(args.md_out) if args.md_out else out_root / "benchmark_summary.md"
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    md_out.write_text(format_benchmark_markdown(summary), encoding="utf-8")

    gate = summary.get("gate", {}) if isinstance(summary, Mapping) else {}
    fail_count = int(gate.get("fail_count", 0)) if isinstance(gate, Mapping) else 0
    print(f"samples={summary.get('sample_count', 0)} gate_fail_count={fail_count}")
    print(f"json={json_out}")
    print(f"md={md_out}")
    if args.strict_gate and fail_count > 0:
        return 1
    return 0


def _summary_stats(values: List[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "median": None, "mean": None, "max": None}
    return {
        "count": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "max": max(values),
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.6f}"
    return str(value)


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
        parsed = int(value.strip(), 10)
    else:
        raise ValueError(f"Field '{field_name}' must be integer-compatible.")
    if parsed < 0:
        raise ValueError(f"Field '{field_name}' must be >= 0.")
    return parsed


def _as_non_negative_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"Field '{field_name}' must be numeric.")
    parsed = float(value)
    if parsed < 0:
        raise ValueError(f"Field '{field_name}' must be >= 0.")
    return parsed


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


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


def _load_json_object(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
