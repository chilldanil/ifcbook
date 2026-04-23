"""Byte-identical determinism gate over all sample IFCs.

Each pipeline run executes in a fresh subprocess for two reasons:
  1. `ifcopenshell.draw` has a teardown bug that segfaults on a second
     in-process invocation; subprocess isolation sidesteps it.
  2. It mirrors how users actually invoke the CLI.

Asserts that two independent runs produce:
  - byte-identical `book.pdf` and every file under `sheets/`,
  - identical `manifest.json` after stripping the (legitimately varying)
    absolute output-dir prefix.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict

import pytest

from .conftest import REPO_ROOT, SAMPLE_IFCS, SAMPLE_PARAMS


DETERMINISTIC_ENV = {
    "LC_ALL": "C.UTF-8",
    "LANG": "C.UTF-8",
    "TZ": "UTC",
    "PYTHONHASHSEED": "0",
    "SOURCE_DATE_EPOCH": "0",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_RUNNER_SCRIPT = (
    "import sys; from ifc_book_prototype.cli import main; "
    "sys.exit(main(sys.argv[1:]))"
)


def _run_pipeline_subprocess(ifc_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **DETERMINISTIC_ENV}
    result = None
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(
            [sys.executable, "-c", _RUNNER_SCRIPT, str(ifc_path), "--out", str(out_dir)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        # IfcOpenShell can intermittently SIGSEGV on process teardown in CI/local.
        # Retry fresh process a small number of times before failing hard.
        if result.returncode == -11 and attempt < max_attempts:
            continue
        break
    assert result is not None
    if result.returncode != 0:
        raise RuntimeError(
            f"pipeline subprocess failed (rc={result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _normalize_manifest(manifest_path: Path, out_dir: Path) -> bytes:
    """Strip the absolute output-dir prefix so two runs into different tmp dirs match."""
    raw = manifest_path.read_text(encoding="utf-8")
    normalized = raw.replace(str(out_dir.resolve()), "<OUT>")
    return normalized.encode("utf-8")


def _hash_artifacts(out_dir: Path) -> Dict[str, str]:
    artifacts: Dict[str, str] = {}
    pdf = out_dir / "book.pdf"
    manifest = out_dir / "manifest.json"
    assert pdf.exists(), "missing book.pdf after pipeline run"
    assert manifest.exists(), "missing manifest.json after pipeline run"
    artifacts["book.pdf"] = _sha256(pdf)
    artifacts["manifest.json[normalized]"] = hashlib.sha256(
        _normalize_manifest(manifest, out_dir)
    ).hexdigest()
    sheets = sorted((out_dir / "sheets").glob("*.svg"))
    assert sheets, "expected at least one sheet SVG"
    for sheet in sheets:
        artifacts[f"sheets/{sheet.name}"] = _sha256(sheet)
    return artifacts


def _first_diff(a: Path, b: Path, n: int = 200) -> str:
    return (
        f"\n  A[{a}] head={a.read_bytes()[:n]!r}"
        f"\n  B[{b}] head={b.read_bytes()[:n]!r}"
    )


@pytest.mark.parametrize("ifc_path", SAMPLE_PARAMS)
def test_pdf_and_sheets_byte_identical(ifc_path: Path, tmp_path: Path) -> None:
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"
    _run_pipeline_subprocess(ifc_path, out_a)
    _run_pipeline_subprocess(ifc_path, out_b)
    hashes_a = _hash_artifacts(out_a)
    hashes_b = _hash_artifacts(out_b)
    assert set(hashes_a) == set(hashes_b), (
        f"artifact set differs:\n  A={sorted(hashes_a)}\n  B={sorted(hashes_b)}"
    )
    diffs = [k for k in hashes_a if hashes_a[k] != hashes_b[k]]
    if diffs:
        # Best-effort head dump for the first diff to speed triage.
        first = diffs[0]
        if first == "manifest.json[normalized]":
            head = (
                f"\n  A normalized manifest:\n{_normalize_manifest(out_a / 'manifest.json', out_a).decode()[:400]}"
                f"\n  B normalized manifest:\n{_normalize_manifest(out_b / 'manifest.json', out_b).decode()[:400]}"
            )
        else:
            head = _first_diff(out_a / first, out_b / first)
        pytest.fail(f"non-deterministic artifacts: {diffs}{head}")


_SMALL_SAMPLES = [
    pytest.param(p, id=p.name) for p in SAMPLE_IFCS if p.name == "Building-Architecture.ifc"
]


@pytest.mark.parametrize("ifc_path", _SMALL_SAMPLES)
def test_ten_rerun_pdf_hash_stable(ifc_path: Path, tmp_path: Path) -> None:
    hashes = []
    for i in range(10):
        out_dir = tmp_path / f"run_{i:02d}"
        _run_pipeline_subprocess(ifc_path, out_dir)
        hashes.append(_sha256(out_dir / "book.pdf"))
    assert len(set(hashes)) == 1, f"book.pdf hash drifted across 10 runs: {sorted(set(hashes))}"
