from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FEATURE_LABEL_TO_CLASS = {
    "Stairs": "IfcStair",
    "Rooms": "IfcSpace",
    "Doors": "IfcDoor",
}

LEGEND_RE = re.compile(r"(?:Replay feature overlay|Feature overlay) \| (?P<body>[^<\n]+)")


@dataclass(frozen=True)
class OverlayGateViolation:
    sheet_id: str
    view_id: str
    ifc_class: str
    expected: int
    rendered: int
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sheet_id": self.sheet_id,
            "view_id": self.view_id,
            "ifc_class": self.ifc_class,
            "expected": self.expected,
            "rendered": self.rendered,
            "source": self.source,
        }


@dataclass(frozen=True)
class OverlayGateObservation:
    sheet_id: str
    view_id: str
    svg_path: Path
    expected_counts: dict[str, int]
    rendered_counts: dict[str, int]
    rendered_symbol_counts: dict[str, int]
    sampled: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "sheet_id": self.sheet_id,
            "view_id": self.view_id,
            "svg_path": str(self.svg_path),
            "expected_counts": self.expected_counts,
            "rendered_counts": self.rendered_counts,
            "rendered_symbol_counts": self.rendered_symbol_counts,
            "sampled": self.sampled,
        }


@dataclass(frozen=True)
class OverlayGateResult:
    run_dir: Path
    passed: bool
    checked_view_count: int
    violation_count: int
    observations: tuple[OverlayGateObservation, ...]
    violations: tuple[OverlayGateViolation, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "PASS" if self.passed else "FAIL",
            "run_dir": str(self.run_dir),
            "checked_view_count": self.checked_view_count,
            "violation_count": self.violation_count,
            "observations": [item.as_dict() for item in self.observations],
            "violations": [item.as_dict() for item in self.violations],
        }


def evaluate_overlay_gate_from_run_dir(
    run_dir: Path,
    *,
    max_count_delta: int = 0,
) -> OverlayGateResult:
    run_dir = run_dir.resolve()
    if max_count_delta < 0:
        raise ValueError("max_count_delta must be non-negative.")

    view_manifest = _load_json(run_dir / "metadata" / "view_manifest.json")
    view_geometry = _load_json(run_dir / "metadata" / "view_geometry.json")
    manifest = _load_json(run_dir / "manifest.json")
    if not isinstance(view_manifest, list):
        raise ValueError("metadata/view_manifest.json must contain a list.")
    if not isinstance(view_geometry, list):
        raise ValueError("metadata/view_geometry.json must contain a list.")
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json must contain an object.")

    geometry_by_view_id = {
        str(item.get("view_id", "")): item
        for item in view_geometry
        if isinstance(item, dict) and item.get("view_id")
    }
    sheet_path_by_id = _sheet_paths_by_id(run_dir, manifest)

    observations: list[OverlayGateObservation] = []
    violations: list[OverlayGateViolation] = []
    for view in view_manifest:
        if not isinstance(view, dict):
            continue
        view_id = str(view.get("view_id", ""))
        sheet_id = str(view.get("sheet_id", ""))
        if not view_id or not sheet_id:
            continue
        geometry = geometry_by_view_id.get(view_id, {})
        if not isinstance(geometry, dict):
            continue
        svg_path = sheet_path_by_id.get(sheet_id)
        if svg_path is None or not svg_path.exists():
            continue
        expected_counts = _expected_feature_counts(geometry)
        rendered_counts, sampled, rendered_symbol_counts = _parse_svg_overlay_counts(svg_path)
        observation = OverlayGateObservation(
            sheet_id=sheet_id,
            view_id=view_id,
            svg_path=svg_path,
            expected_counts=expected_counts,
            rendered_counts=rendered_counts,
            rendered_symbol_counts=rendered_symbol_counts,
            sampled=sampled,
        )
        observations.append(observation)
        violations.extend(
            _count_violations(
                sheet_id=sheet_id,
                view_id=view_id,
                expected_counts=expected_counts,
                rendered_counts=rendered_counts,
                rendered_symbol_counts=rendered_symbol_counts,
                sampled=sampled,
                max_count_delta=max_count_delta,
            )
        )

    return OverlayGateResult(
        run_dir=run_dir,
        passed=not violations,
        checked_view_count=len(observations),
        violation_count=len(violations),
        observations=tuple(observations),
        violations=tuple(violations),
    )


def format_overlay_gate_human(result: OverlayGateResult) -> str:
    lines = [
        f"OVERLAY_GATE {'PASS' if result.passed else 'FAIL'} run_dir={result.run_dir}",
        f"checked_view_count={result.checked_view_count}",
        f"violation_count={result.violation_count}",
    ]
    if result.violations:
        lines.append("violations:")
        for violation in result.violations:
            lines.append(
                "  "
                f"sheet={violation.sheet_id} view={violation.view_id} "
                f"class={violation.ifc_class} expected={violation.expected} "
                f"rendered={violation.rendered} source={violation.source}"
            )
    return "\n".join(lines)


def format_overlay_gate_machine(result: OverlayGateResult) -> str:
    return json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":"))


def _load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist.")
    return json.loads(path.read_text(encoding="utf-8"))


def _sheet_paths_by_id(run_dir: Path, manifest: dict) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for sheet in manifest.get("sheets", []):
        if not isinstance(sheet, dict):
            continue
        sheet_id = str(sheet.get("sheet_id", ""))
        if not sheet_id:
            continue
        svg_path = Path(str(sheet.get("svg_path", "")))
        candidates = [svg_path]
        if svg_path.name:
            candidates.append(run_dir / "sheets" / svg_path.name)
        for candidate in candidates:
            if candidate.exists():
                result[sheet_id] = candidate.resolve()
                break
    return result


def _expected_feature_counts(geometry: dict) -> dict[str, int]:
    raw_counts = geometry.get("feature_anchor_counts", {})
    if not isinstance(raw_counts, dict):
        return {}
    return {
        str(class_name): int(count or 0)
        for class_name, count in raw_counts.items()
        if class_name in FEATURE_LABEL_TO_CLASS.values()
    }


def _parse_svg_overlay_counts(svg_path: Path) -> tuple[dict[str, int], bool, dict[str, int]]:
    text = svg_path.read_text(encoding="utf-8")
    match = LEGEND_RE.search(text)
    rendered_counts: dict[str, int] = {}
    sampled = False
    if match:
        body = match.group("body")
        sampled = "(sampled)" in body
        body = body.replace("(sampled)", "")
        for part in body.split(" | "):
            if ":" not in part:
                continue
            label, value = part.split(":", 1)
            class_name = FEATURE_LABEL_TO_CLASS.get(label.strip())
            if class_name is None:
                continue
            value = value.strip()
            if value == "off":
                continue
            try:
                rendered_counts[class_name] = int(value)
            except ValueError:
                continue
    rendered_symbol_counts = {
        "IfcDoor": text.count('data-feature="door-arc"'),
    }
    return rendered_counts, sampled, rendered_symbol_counts


def _count_violations(
    *,
    sheet_id: str,
    view_id: str,
    expected_counts: dict[str, int],
    rendered_counts: dict[str, int],
    rendered_symbol_counts: dict[str, int],
    sampled: bool,
    max_count_delta: int,
) -> list[OverlayGateViolation]:
    violations: list[OverlayGateViolation] = []
    for class_name, rendered in sorted(rendered_counts.items()):
        if class_name not in expected_counts:
            continue
        expected = expected_counts[class_name]
        if abs(expected - rendered) > max_count_delta:
            violations.append(
                OverlayGateViolation(
                    sheet_id=sheet_id,
                    view_id=view_id,
                    ifc_class=class_name,
                    expected=expected,
                    rendered=rendered,
                    source="legend",
                )
            )
    if not sampled and "IfcDoor" in rendered_counts:
        rendered_symbols = rendered_symbol_counts.get("IfcDoor", 0)
        rendered_legend = rendered_counts["IfcDoor"]
        if abs(rendered_legend - rendered_symbols) > max_count_delta:
            violations.append(
                OverlayGateViolation(
                    sheet_id=sheet_id,
                    view_id=view_id,
                    ifc_class="IfcDoor",
                    expected=rendered_legend,
                    rendered=rendered_symbols,
                    source="svg_symbol_count",
                )
            )
    return violations
