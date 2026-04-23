"""Unit tests for OCCT-side determinism primitives.

These do not require pythonocc-core: ``quantize`` and ``sort_lines_canonical``
are pure-Python helpers that live in occt_section.py so they share the same
discipline as the OCCT-touching code, but they have no OCCT dependency.
"""
from __future__ import annotations

import random

from ifc_book_prototype.domain import LineKind, LineweightClass, Point2D, TypedLine2D
from ifc_book_prototype.occt_section import quantize, sort_lines_canonical


def test_quantize_is_stable_across_calls():
    expected = quantize(0.123456789)
    for _ in range(1000):
        assert quantize(0.123456789) == expected


def test_quantize_is_idempotent():
    for raw in (0.0, 0.123456789, -0.987654321, 1234.567, 1e-7, -1e-7):
        once = quantize(raw)
        twice = quantize(once)
        assert once == twice, f"non-idempotent: {raw} -> {once} -> {twice}"


def test_quantize_grid_default_is_1e_5():
    # 0.123456789 quantized at 1e-5 grid is 0.12346 (rounded half-away-from-zero).
    # IEEE 754: `12346 * 1e-5` is 0.12346000000000001, well within 1e-9 tolerance.
    import math
    assert math.isclose(quantize(0.123456789), 0.12346, abs_tol=1e-9)


def _make_line(idx: int, kind: LineKind, ifc_class: str) -> TypedLine2D:
    return TypedLine2D(
        kind=kind,
        lineweight_class=LineweightClass.HEAVY,
        points=[Point2D(x=float(idx), y=float(idx)), Point2D(x=float(idx + 1), y=float(idx))],
        source_element=f"GLOBAL_{idx:04d}",
        source_ifc_class=ifc_class,
    )


def test_sort_lines_canonical_is_stable_under_shuffle():
    lines = [
        _make_line(i, LineKind.CUT if i % 2 == 0 else LineKind.PROJECTED, "IfcWall" if i % 3 == 0 else "IfcSlab")
        for i in range(50)
    ]
    expected = sort_lines_canonical(lines)
    rng = random.Random(0)
    for _ in range(20):
        shuffled = list(lines)
        rng.shuffle(shuffled)
        assert sort_lines_canonical(shuffled) == expected
