from __future__ import annotations

import argparse
from pathlib import Path

from .bundle_replay import replay_bundle
from .pipeline import PrototypePipeline
from .profiles import load_style_profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prototype IFC drawing-book pipeline")
    parser.add_argument("ifc_path", nargs="?", help="Path to the input IFC SPF file")
    parser.add_argument("--out", required=True, help="Output directory for generated artifacts")
    parser.add_argument("--profile", help="Path to a JSON style profile")
    parser.add_argument("--bundle", help="Path to an existing generated bundle to replay without reopening the IFC")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_dir = Path(args.out)
    if args.bundle:
        if args.ifc_path:
            parser.error("Specify either an IFC path or --bundle, not both.")
        bundle_dir = Path(args.bundle)
        if not bundle_dir.exists():
            parser.error(f"Bundle directory does not exist: {bundle_dir}")
        manifest = replay_bundle(bundle_dir=bundle_dir, output_dir=output_dir)
    else:
        if not args.ifc_path:
            parser.error("Either an IFC path or --bundle is required.")
        ifc_path = Path(args.ifc_path)
        if not ifc_path.exists():
            parser.error(f"Input IFC does not exist: {ifc_path}")
        profile = load_style_profile(args.profile)
        manifest = PrototypePipeline(profile).run(ifc_path=ifc_path, output_dir=output_dir)

    print(f"job_id={manifest.job_id}")
    print(f"output_dir={manifest.output_dir}")
    print(f"pdf={manifest.pdf_path}")
    print("sheets:")
    for sheet in manifest.sheets:
        print(f"  {sheet.sheet_id} -> {sheet.svg_path}")
    return 0
