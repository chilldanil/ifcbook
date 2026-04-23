from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bundle_replay import replay_bundle
from .pipeline import PrototypePipeline
from .profiles import load_style_profile


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
    print(f"fallback.timeout_events={fallback.get('timeout_events', 0)}")
    print(f"fallback.exception_events={fallback.get('exception_events', 0)}")
    print(f"fallback.empty_events={fallback.get('empty_events', 0)}")
    by_class = fallback.get("by_class", {}) or {}
    if by_class:
        print("fallback.by_class:")
        for class_name, count in sorted(by_class.items()):
            print(f"  {class_name}: {count}")
    else:
        print("fallback.by_class: (none)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.summarize_runtime:
        return _summarize_runtime(Path(args.summarize_runtime))

    if not args.out:
        parser.error("--out is required unless --summarize-runtime is used.")

    output_dir = Path(args.out)
    profile = load_style_profile(args.profile)
    if args.bundle:
        if args.ifc_path:
            parser.error("Specify either an IFC path or --bundle, not both.")
        bundle_dir = Path(args.bundle)
        if not bundle_dir.exists():
            parser.error(f"Bundle directory does not exist: {bundle_dir}")
        manifest = replay_bundle(bundle_dir=bundle_dir, output_dir=output_dir, profile=profile)
    else:
        if not args.ifc_path:
            parser.error("Either an IFC path or --bundle is required.")
        ifc_path = Path(args.ifc_path)
        if not ifc_path.exists():
            parser.error(f"Input IFC does not exist: {ifc_path}")
        manifest = PrototypePipeline(profile).run(ifc_path=ifc_path, output_dir=output_dir)

    print(f"job_id={manifest.job_id}")
    print(f"output_dir={manifest.output_dir}")
    print(f"pdf={manifest.pdf_path}")
    print("sheets:")
    for sheet in manifest.sheets:
        print(f"  {sheet.sheet_id} -> {sheet.svg_path}")
    return 0
