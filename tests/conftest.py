"""Pytest configuration: deterministic environment + sample IFC discovery."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List

import pytest


# --- Determinism pinning (executed at import time, before pipeline modules load) ----
os.environ.setdefault("LC_ALL", "C.UTF-8")
os.environ.setdefault("LANG", "C.UTF-8")
os.environ.setdefault("TZ", "UTC")
os.environ.setdefault("PYTHONHASHSEED", "0")
os.environ.setdefault("SOURCE_DATE_EPOCH", "0")
try:
    time.tzset()  # POSIX only
except AttributeError:
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "samples"


def _discover_samples() -> List[Path]:
    if not SAMPLES_DIR.is_dir():
        return []
    return sorted(p for p in SAMPLES_DIR.glob("*.ifc") if p.is_file())


SAMPLE_IFCS = _discover_samples()

# Hochvolthaus is the 70 MB sample — only run it under the `slow` marker.
_SLOW_SAMPLES = {"new251211_Hochvolthaus_Group01_03.ifc"}


def sample_id(path: Path) -> str:
    return path.name


def sample_param(path: Path):
    marks = []
    if path.name in _SLOW_SAMPLES:
        marks.append(pytest.mark.slow)
    return pytest.param(path, id=path.name, marks=marks)


SAMPLE_PARAMS = [sample_param(p) for p in SAMPLE_IFCS]


@pytest.fixture(scope="session")
def sample_ifcs() -> List[Path]:
    return list(SAMPLE_IFCS)


def run_pipeline(ifc_path: Path, out_dir: Path):
    """Run the prototype pipeline against `ifc_path` into `out_dir`. Returns the manifest."""
    # Imported lazily so the env vars above apply before pipeline modules read os.environ.
    from ifc_book_prototype.pipeline import PrototypePipeline
    from ifc_book_prototype.profiles import load_style_profile

    out_dir.mkdir(parents=True, exist_ok=True)
    profile = load_style_profile()
    return PrototypePipeline(profile).run(ifc_path, out_dir)
