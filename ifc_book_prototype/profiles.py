from __future__ import annotations

import json
from pathlib import Path

from .domain import FeatureOverlayRule, FloorPlanRule, PageSpec, StyleProfile


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_PROFILE_PATH = (
    PACKAGE_ROOT
    / "profiles"
    / "din_iso_arch_floor_plan_v3_phase3c_owned_projection_hidden.json"
)

PROFILE_PRESETS = {
    "default": DEFAULT_PROFILE_PATH,
    "din_iso": DEFAULT_PROFILE_PATH,
    "presentation": PACKAGE_ROOT / "profiles" / "office_presentation_rerender_v1.json",
    "permit_set": PACKAGE_ROOT / "profiles" / "office_permit_set_rerender_v1.json",
    "coordination": PACKAGE_ROOT / "profiles" / "office_coordination_rerender_v1.json",
}


def available_profile_presets() -> dict[str, Path]:
    return dict(sorted(PROFILE_PRESETS.items()))


def resolve_style_profile_path(profile_path: str | None = None) -> Path:
    if profile_path is None:
        return DEFAULT_PROFILE_PATH
    return PROFILE_PRESETS.get(profile_path, Path(profile_path))


def load_style_profile(profile_path: str | None = None) -> StyleProfile:
    path = resolve_style_profile_path(profile_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    page = PageSpec(**raw["page"])
    floor_plan_raw = dict(raw["floor_plan"])
    feature_overlay_raw = floor_plan_raw.pop("feature_overlay", {})
    feature_overlay = FeatureOverlayRule(**feature_overlay_raw)
    floor_plan = FloorPlanRule(feature_overlay=feature_overlay, **floor_plan_raw)
    return StyleProfile(
        profile_id=raw["profile_id"],
        region=raw["region"],
        page=page,
        lineweights_mm=raw["lineweights_mm"],
        floor_plan=floor_plan,
        sheet_prefix=raw["sheet_prefix"],
        cover_sheet_id=raw["cover_sheet_id"],
        index_sheet_id=raw["index_sheet_id"],
    )
