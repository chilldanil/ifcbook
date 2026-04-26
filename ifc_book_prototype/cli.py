from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bundle_replay import replay_bundle
from .domain import PipelineManifest
from .pipeline import PrototypePipeline
from .profiles import load_style_profile
from .progress_plan import (
    create_progress_plan_from_run_root,
    format_progress_plan_human,
    format_progress_plan_markdown,
    format_progress_plan_svg,
)
from .runtime_gate import (
    RuntimeGateThresholds,
    evaluate_runtime_gate_from_run_dir,
    format_runtime_gate_human,
    format_runtime_gate_machine,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prototype IFC drawing-book pipeline")
    parser.add_argument("ifc_path", nargs="?", help="Path to the input IFC SPF file")
    parser.add_argument("--out", help="Output directory for generated artifacts")
    parser.add_argument("--profile", help="Path to a JSON style profile")
    parser.add_argument("--bundle", help="Path to an existing generated bundle to replay without reopening the IFC")
    parser.add_argument(
        "--summarize-runtime",
        metavar="RUN_DIR",
        help=(
            "Print a terse summary of metadata/geometry_runtime_summary.json from an existing "
            "pipeline run directory. Intended for Phase 3A OCCT-worker validation."
        ),
    )
    parser.add_argument(
        "--runtime-gate",
        metavar="RUN_DIR",
        help=(
            "Evaluate metadata/geometry_runtime_summary.json in RUN_DIR against runtime/"
            "fallback thresholds. Returns non-zero on threshold violations."
        ),
    )
    parser.add_argument(
        "--max-fallback-event-rate",
        type=float,
        help="Gate threshold: maximum allowed fallback event rate (events_total / view_count).",
    )
    parser.add_argument(
        "--max-timeout-events-total",
        type=int,
        help="Gate threshold: maximum allowed fallback timeout events total.",
    )
    parser.add_argument(
        "--min-occt-coverage-rate",
        type=float,
        help="Gate threshold: minimum required OCCT coverage rate (occt_view_count / view_count).",
    )
    parser.add_argument(
        "--min-hidden-lines-total",
        type=int,
        help="Gate threshold: minimum required hidden line count (linework_counts_total.HIDDEN).",
    )
    parser.add_argument(
        "--min-hidden-line-ratio",
        type=float,
        help="Gate threshold: minimum required hidden line ratio (hidden_lines_total / linework_lines_total).",
    )
    parser.add_argument(
        "--plan-next",
        metavar="RUN_ROOT",
        help=(
            "Build a progress plan from per-sample run artifacts under RUN_ROOT. Scans for "
            "metadata/geometry_runtime_summary.json and optional metadata/runtime_gate_result.json."
        ),
    )
    parser.add_argument(
        "--plan-next-out",
        help="Optional markdown output path for --plan-next report.",
    )
    parser.add_argument(
        "--plan-next-json-out",
        help="Optional JSON output path for --plan-next report.",
    )
    parser.add_argument(
        "--plan-next-svg-out",
        help="Optional SVG output path for --plan-next report.",
    )
    return parser


def _summarize_runtime(run_dir: Path) -> int:
    summary_path = run_dir / "metadata" / "geometry_runtime_summary.json"
    if not summary_path.exists():
        print(f"ERROR: {summary_path} does not exist.")
        return 2
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    backend_counts = data.get("backend_counts", {}) or {}
    fallback = data.get("fallback", {}) or {}
    print(f"run_dir={run_dir}")
    print(f"view_count={data.get('view_count', 0)}")
    print(f"occt_view_count={data.get('occt_view_count', 0)}")
    print("backend_counts:")
    for name, count in sorted(backend_counts.items()):
        print(f"  {name}: {count}")
    print(f"fallback.events_total={fallback.get('events_total', 0)}")
    print(
        "fallback.timeout_events_total="
        f"{fallback.get('timeout_events_total', fallback.get('timeout_events', 0))}"
    )
    print(
        "fallback.exception_events_total="
        f"{fallback.get('exception_events_total', fallback.get('exception_events', 0))}"
    )
    print(
        "fallback.empty_events_total="
        f"{fallback.get('empty_events_total', fallback.get('empty_events', 0))}"
    )
    by_class = fallback.get("by_class", {}) or {}
    if by_class:
        print("fallback.by_class:")
        for class_name, count in sorted(by_class.items()):
            print(f"  {class_name}: {count}")
    else:
        print("fallback.by_class: (none)")
    return 0


def run_pipeline_job(
    *,
    output_dir: Path,
    profile_path: str | None = None,
    ifc_path: Path | None = None,
    bundle_dir: Path | None = None,
) -> PipelineManifest:
    profile = load_style_profile(profile_path)
    if bundle_dir is not None:
        if ifc_path is not None:
            raise ValueError("Specify either an IFC path or --bundle, not both.")
        if not bundle_dir.exists():
            raise FileNotFoundError(f"Bundle directory does not exist: {bundle_dir}")
        return replay_bundle(bundle_dir=bundle_dir, output_dir=output_dir, profile=profile)

    if ifc_path is None:
        raise ValueError("Either an IFC path or --bundle is required.")
    if not ifc_path.exists():
        raise FileNotFoundError(f"Input IFC does not exist: {ifc_path}")
    return PrototypePipeline(profile).run(ifc_path=ifc_path, output_dir=output_dir)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.plan_next_out and not args.plan_next:
        parser.error("--plan-next-out requires --plan-next.")
    if args.plan_next_json_out and not args.plan_next:
        parser.error("--plan-next-json-out requires --plan-next.")
    if args.plan_next_svg_out and not args.plan_next:
        parser.error("--plan-next-svg-out requires --plan-next.")

    if args.summarize_runtime:
        return _summarize_runtime(Path(args.summarize_runtime))

    if args.runtime_gate:
        thresholds = RuntimeGateThresholds(
            max_fallback_event_rate=args.max_fallback_event_rate,
            max_timeout_events_total=args.max_timeout_events_total,
            min_occt_coverage_rate=args.min_occt_coverage_rate,
            min_hidden_lines_total=args.min_hidden_lines_total,
            min_hidden_line_ratio=args.min_hidden_line_ratio,
        )
        if not thresholds.has_any_limit():
            parser.error(
                "At least one threshold is required with --runtime-gate "
                "(--max-fallback-event-rate / --max-timeout-events-total / "
                "--min-occt-coverage-rate / --min-hidden-lines-total / "
                "--min-hidden-line-ratio)."
            )
        try:
            result = evaluate_runtime_gate_from_run_dir(
                Path(args.runtime_gate),
                thresholds=thresholds,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"ERROR: {exc}")
            return 2
        print(format_runtime_gate_human(result))
        print(f"RUNTIME_GATE_JSON={format_runtime_gate_machine(result)}")
        return 0 if result.passed else 1

    if args.plan_next:
        try:
            plan = create_progress_plan_from_run_root(Path(args.plan_next))
        except (FileNotFoundError, ValueError) as exc:
            print(f"ERROR: {exc}")
            return 2
        print(format_progress_plan_human(plan))
        if args.plan_next_out:
            plan_out_path = Path(args.plan_next_out)
            plan_out_path.parent.mkdir(parents=True, exist_ok=True)
            plan_out_path.write_text(format_progress_plan_markdown(plan), encoding="utf-8")
            print(f"plan_next_report={plan_out_path}")
        if args.plan_next_json_out:
            plan_json_path = Path(args.plan_next_json_out)
            plan_json_path.parent.mkdir(parents=True, exist_ok=True)
            plan_json_path.write_text(
                json.dumps(plan.as_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"plan_next_json={plan_json_path}")
        if args.plan_next_svg_out:
            plan_svg_path = Path(args.plan_next_svg_out)
            plan_svg_path.parent.mkdir(parents=True, exist_ok=True)
            plan_svg_path.write_text(format_progress_plan_svg(plan), encoding="utf-8")
            print(f"plan_next_svg={plan_svg_path}")
        return 0

    if not args.out:
        parser.error(
            "--out is required unless --summarize-runtime, --runtime-gate, or --plan-next is used."
        )

    output_dir = Path(args.out)
    ifc_path = Path(args.ifc_path) if args.ifc_path else None
    bundle_dir = Path(args.bundle) if args.bundle else None
    try:
        manifest = run_pipeline_job(
            output_dir=output_dir,
            profile_path=args.profile,
            ifc_path=ifc_path,
            bundle_dir=bundle_dir,
        )
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))

    print(f"job_id={manifest.job_id}")
    print(f"output_dir={manifest.output_dir}")
    print(f"pdf={manifest.pdf_path}")
    print("sheets:")
    for sheet in manifest.sheets:
        print(f"  {sheet.sheet_id} -> {sheet.svg_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
