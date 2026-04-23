from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import run_pipeline


def test_view_geometry_emits_feature_anchor_counts(tmp_path: Path):
    sample = Path("samples/Building-Architecture.ifc")
    if not sample.exists():
        pytest.skip("sample IFC not found")

    out_dir = tmp_path / "run"
    run_pipeline(sample, out_dir)
    view_geometry = json.loads((out_dir / "metadata" / "view_geometry.json").read_text(encoding="utf-8"))
    assert isinstance(view_geometry, list) and view_geometry
    assert any((item.get("feature_anchor_counts", {}).get("IfcSpace", 0) > 0) for item in view_geometry)
