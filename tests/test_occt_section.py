"""OCCT-dependent integration tests.

Skipped automatically when ``pythonocc-core`` is not importable so the
default PR gate stays green for contributors without the [occt] extra.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import REPO_ROOT, SAMPLE_IFCS
from .test_determinism import _RUNNER_SCRIPT, _sha256, DETERMINISTIC_ENV

occt_section = pytest.importorskip("ifc_book_prototype.occt_section")
if not occt_section.OCCT_AVAILABLE:
    pytest.skip("pythonocc-core not available", allow_module_level=True)

pytestmark = pytest.mark.occt


# ---------------------------------------------------------------------------
# Edge sampler determinism
# ---------------------------------------------------------------------------


def test_edge_sampler_is_stable_on_unit_circle():
    """A unit-circle edge sampled at 5e-4 chord tol must yield the same vertex
    count and the same first point across 10 repetitions.
    """
    from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Circ  # type: ignore
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeEdge  # type: ignore

    axis = gp_Ax2(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0))
    circ = gp_Circ(axis, 1.0)
    edge = BRepBuilderAPI_MakeEdge(circ).Edge()
    first_run = occt_section.edge_to_polyline(edge, 5.0e-4)
    assert len(first_run) >= 2
    for _ in range(9):
        again = occt_section.edge_to_polyline(edge, 5.0e-4)
        assert again == first_run


# ---------------------------------------------------------------------------
# Composite backend produces CUT linework
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ifc_path",
    [pytest.param(p, id=p.name) for p in SAMPLE_IFCS if p.name == "Building-Architecture.ifc"],
)
def test_composite_emits_wall_cut_lines(ifc_path: Path):
    from ifc_book_prototype.geometry_backend import create_geometry_backend
    from ifc_book_prototype.profiles import load_style_profile

    profile = load_style_profile()
    backend = create_geometry_backend(ifc_path, profile.floor_plan.include_classes, profile=profile)
    assert backend.__class__.__name__ == "CompositeGeometryBackend", (
        f"expected composite backend, got {backend.__class__.__name__}"
    )
    # Build a representative view from the first storey and look for any
    # IfcWall CUT line.
    from ifc_book_prototype.pipeline import PrototypePipeline

    pipeline = PrototypePipeline(profile)
    preflight, scan = pipeline._preflight(ifc_path)  # noqa: SLF001
    normalized = pipeline._normalize(scan, preflight)  # noqa: SLF001
    views = pipeline._plan_views(normalized)  # noqa: SLF001
    assert views, "no views planned"

    found_wall_cut = False
    for view in views:
        summary = backend.build_view(view)
        if summary.linework is None:
            continue
        for line in summary.linework.lines:
            if line.kind.name == "CUT" and line.source_ifc_class == "IfcWall":
                found_wall_cut = True
                break
        if found_wall_cut:
            break
    assert found_wall_cut, "OCCT composite backend produced no IfcWall CUT lines"


# ---------------------------------------------------------------------------
# Determinism gate with OCCT active (subprocess to isolate ifcopenshell.draw)
# ---------------------------------------------------------------------------


def _run_pipeline_subprocess(ifc_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **DETERMINISTIC_ENV}
    result = subprocess.run(
        [sys.executable, "-c", _RUNNER_SCRIPT, str(ifc_path), "--out", str(out_dir)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pipeline subprocess failed (rc={result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


@pytest.mark.parametrize(
    "ifc_path",
    [pytest.param(p, id=p.name) for p in SAMPLE_IFCS if p.name == "Building-Architecture.ifc"],
)
def test_occt_pipeline_is_byte_identical_across_ten_runs(ifc_path: Path, tmp_path: Path):
    hashes = []
    for i in range(10):
        out_dir = tmp_path / f"run_{i:02d}"
        _run_pipeline_subprocess(ifc_path, out_dir)
        hashes.append(_sha256(out_dir / "book.pdf"))
    assert len(set(hashes)) == 1, f"book.pdf hash drifted across 10 OCCT runs: {sorted(set(hashes))}"


# ---------------------------------------------------------------------------
# Timeout fallback path is exercised
# ---------------------------------------------------------------------------


def test_budget_exceeded_triggers_fallback(monkeypatch):
    """Monkeypatch section_shape to sleep past the budget; assert the fallback
    note ends up on the resulting TypedLine2D.
    """
    import time

    from ifc_book_prototype.domain import LineKind

    def _slow_section(shape, face):
        time.sleep(5.0)
        return []

    monkeypatch.setattr(occt_section, "section_shape", _slow_section)

    class _FakeElement:
        def __init__(self, gid):
            self._gid = gid
            self.GlobalId = gid

        def is_a(self):
            return "IfcWall"

        def id(self):
            return 1

    fallback_called = []

    def _fallback(element):
        fallback_called.append(element.GlobalId)
        return [[(0.0, 0.0), (1.0, 0.0)]]

    # The OCCT-touching helpers we don't want to call in this test:
    monkeypatch.setattr(occt_section, "build_cut_face", lambda plane, extent: object())
    monkeypatch.setattr(
        occt_section,
        "brep_from_ifc_element",
        lambda mod, settings, element: object(),
    )
    monkeypatch.setattr(occt_section, "edge_to_polyline", lambda edge, tol: [])

    plane = occt_section.CutPlane(z_m=0.0)
    lines = occt_section.extract_cut_lines(
        ifc_geom_module=None,
        elements=[_FakeElement("0xWALL_TIMEOUT")],
        plane=plane,
        per_element_budget_s=0.2,
        chord_tol_m=5.0e-4,
        fallback=_fallback,
    )
    assert fallback_called == ["0xWALL_TIMEOUT"]
    assert lines, "fallback should still produce a TypedLine2D"
    assert any("timed out" in note for line in lines for note in line.notes)
    assert all(line.kind == LineKind.CUT for line in lines)
