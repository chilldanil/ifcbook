from __future__ import annotations

import json
from pathlib import Path

from .domain import FeatureOverlayRule, FloorPlanRule, PageSpec, StyleProfile


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_PROFILE_PATH = PACKAGE_ROOT / "profiles" / "din_iso_arch_floor_plan_v1.json"


def load_style_profile(profile_path: str | None = None) -> StyleProfile:
    path = Path(profile_path) if profile_path else DEFAULT_PROFILE_PATH
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
