"""OCCT BRep section extraction for floor-plan cut geometry.

All `pythonocc-core` interaction is funneled through this module. It is
import-safe even when `pythonocc-core` is not installed: in that case
``OCCT_AVAILABLE`` is False and ``extract_cut_lines`` raises ``RuntimeError``.

Determinism discipline (run at first import when OCCT is available):
  - Disable OCCT thread parallelism on every relevant boolean algorithm.
  - Disable parallel meshing default.
  - Suppress the OCCT FPE signal handler so it never alters Python's float
    behavior.
  - Pin the global OCCT thread pool to a single worker when the binding
    exposes it.

Geometry discipline:
  - Quantize every emitted coordinate to a 1e-5 m grid.
  - Sort emitted edges by a content key, then chain greedy.
  - Sort the resulting typed lines via ``typed_line_sort_key``.
"""
from __future__ import annotations

import logging
import math
import multiprocessing
import os
import signal
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .domain import LineKind, LineweightClass, Point2D, TypedLine2D, typed_line_sort_key

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OCCT availability + import-time discipline
# ---------------------------------------------------------------------------

OCCT_AVAILABLE = False
_OCCT_IMPORT_ERROR: Optional[BaseException] = None

try:
    # Geometry primitives
    from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Pln  # type: ignore
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeFace  # type: ignore
    from OCC.Core.BRepAlgoAPI import (  # type: ignore
        BRepAlgoAPI_Section,
        BRepAlgoAPI_BuilderAlgo,
        BRepAlgoAPI_Fuse,
        BRepAlgoAPI_Cut,
    )
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve  # type: ignore
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh  # type: ignore
    from OCC.Core.BRepTools import breptools_Read  # type: ignore
    from OCC.Core.BRep import BRep_Builder  # type: ignore
    from OCC.Core.GCPnts import GCPnts_QuasiUniformDeflection  # type: ignore
    from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Edge, TopoDS_Face  # type: ignore
    from OCC.Core.TopExp import TopExp_Explorer  # type: ignore
    from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_VERTEX  # type: ignore
    from OCC.Core.OSD import OSD  # type: ignore

    # --- Determinism discipline -------------------------------------------------
    for _algo in (BRepAlgoAPI_BuilderAlgo, BRepAlgoAPI_Section, BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut):
        try:
            _algo.SetRunParallel(False)
        except Exception:  # pragma: no cover - older bindings
            pass
    try:
        BRepMesh_IncrementalMesh.SetParallelDefault(False)
    except Exception:  # pragma: no cover
        pass
    try:
        OSD.SetSignal(False)
    except Exception:  # pragma: no cover
        pass
    try:  # pragma: no cover - guarded; not all bindings expose this
        from OCC.Core.OSD import OSD_ThreadPool  # type: ignore
        if hasattr(OSD_ThreadPool, "DefaultPool"):
            OSD_ThreadPool.DefaultPool().Init(1)
    except Exception as _pool_exc:
        _LOG.debug("OCCT thread pool pinning unavailable: %s", _pool_exc)

    OCCT_AVAILABLE = True

except Exception as _exc:  # pragma: no cover - exercised only without OCCT
    _OCCT_IMPORT_ERROR = _exc


# ---------------------------------------------------------------------------
# Quantization + canonical sort
# ---------------------------------------------------------------------------

QUANTIZATION_M = 1.0e-5


def quantize(value: float, grid: float = QUANTIZATION_M) -> float:
    """Round to a fixed grid; idempotent."""
    return math.floor(value / grid + 0.5) * grid


def quantize_point(x: float, y: float, grid: float = QUANTIZATION_M) -> Tuple[float, float]:
    return quantize(x, grid), quantize(y, grid)


def sort_lines_canonical(lines: Sequence[TypedLine2D]) -> List[TypedLine2D]:
    """Sort using the public typed_line_sort_key so renderer + serializer agree."""
    return sorted(lines, key=typed_line_sort_key)


# ---------------------------------------------------------------------------
# Per-call wall-clock budget
# ---------------------------------------------------------------------------


class BudgetExceeded(TimeoutError):
    """Raised when an OCCT call exceeds its per-element budget."""


def _on_main_thread() -> bool:
    return threading.current_thread() is threading.main_thread() and os.name == "posix"


def run_with_budget(fn: Callable[[], object], budget_s: float):
    """Run ``fn`` under a wall-clock budget.

    Strategy:
      - On a POSIX main thread we install a SIGALRM that raises
        ``BudgetExceeded``. This is the cheap path.
      - Off-main-thread (e.g. inside a worker) we fall back to a
        ``multiprocessing.Process`` so we still get a hard cap. The fallback
        is heavier; the fast path is the expected one.
    """
    if budget_s <= 0:
        return fn()

    if _on_main_thread():
        previous = signal.signal(signal.SIGALRM, _raise_budget_exceeded)
        signal.setitimer(signal.ITIMER_REAL, budget_s)
        try:
            return fn()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, previous)

    # Off-main-thread fallback: bounce into a subprocess. Caller's `fn` must
    # be picklable for this path; OCCT shapes are not, so callers should keep
    # OCCT work on the main thread whenever feasible.
    return _run_in_process(fn, budget_s)


def _raise_budget_exceeded(signum, frame):  # noqa: D401, ARG001
    raise BudgetExceeded("OCCT call exceeded per-element wall-clock budget")


def _run_in_process(fn: Callable[[], object], budget_s: float):
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()

    def _target(q):
        try:
            q.put(("ok", fn()))
        except BaseException as exc:  # pragma: no cover
            q.put(("err", repr(exc)))

    process = ctx.Process(target=_target, args=(queue,))
    process.start()
    process.join(budget_s)
    if process.is_alive():
        process.terminate()
        process.join(0.5)
        raise BudgetExceeded("OCCT subprocess exceeded per-element wall-clock budget")
    if not queue.empty():
        kind, payload = queue.get()
        if kind == "ok":
            return payload
        raise RuntimeError(f"OCCT subprocess error: {payload}")
    raise RuntimeError("OCCT subprocess produced no result")


# ---------------------------------------------------------------------------
# OCCT primitives (only callable when OCCT_AVAILABLE)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CutPlane:
    z_m: float
    normal: Tuple[float, float, float] = (0.0, 0.0, 1.0)


@dataclass(frozen=True)
class CutExtractionReport:
    lines: List[TypedLine2D]
    fallback_events: int
    fallback_by_class: Dict[str, int]
    fallback_timeout_events: int
    fallback_exception_events: int
    fallback_empty_events: int
    fallback_line_count: int


def _require_occt() -> None:
    if not OCCT_AVAILABLE:
        raise RuntimeError(
            f"pythonocc-core is not available: {_OCCT_IMPORT_ERROR!r}. "
            "Install the [occt] extra to enable OCCT cut extraction."
        )


def build_cut_face(plane: CutPlane, xy_extent_m: float):
    """Construct a finite planar face large enough to slice the model bbox."""
    _require_occt()
    origin = gp_Pnt(0.0, 0.0, plane.z_m)
    normal = gp_Dir(*plane.normal)
    pln = gp_Pln(origin, normal)
    # Half-extent on each side; enlarge a bit to avoid edge tangency.
    half = max(xy_extent_m, 1.0) * 1.1
    maker = BRepBuilderAPI_MakeFace(pln, -half, half, -half, half)
    return maker.Face()


def _set_ifc_geom_setting(local_settings, key_name: str, value) -> bool:
    """Set an IfcOpenShell geometry setting across old/new APIs.

    Older bindings expose enum-like attributes such as ``USE_WORLD_COORDS``.
    Newer bindings use string keys such as ``use-world-coords``.
    """
    # Old API: settings.set(settings.USE_WORLD_COORDS, True)
    if hasattr(local_settings, key_name):
        try:
            local_settings.set(getattr(local_settings, key_name), value)
            return True
        except Exception:
            pass

    # New API: settings.set("use-world-coords", True)
    key_hyphen = key_name.lower().replace("_", "-")
    for candidate in (key_hyphen, key_name):
        try:
            local_settings.set(candidate, value)
            return True
        except Exception:
            continue
    return False


def _read_brep_text_to_shape(brep_data: str):
    """Deserialize ASCII BRep text into ``TopoDS_Shape``."""
    builder = BRep_Builder()
    shape = TopoDS_Shape()
    # `breptools_Read` can take a string buffer in many bindings; we use a
    # tmpfile path as the most portable form across OCCT versions.
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".brep", delete=False) as handle:
        handle.write(brep_data)
        tmp_path = handle.name
    try:
        ok = breptools_Read(shape, tmp_path, builder)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    if not ok:
        return None
    try:
        if shape.IsNull():
            return None
    except Exception:
        pass
    return shape


def _coerce_occt_shape(raw) -> Optional[object]:
    """Extract an OCCT shape from IfcOpenShell return values."""
    if raw is None:
        return None

    # New API path: create_shape(...).geometry is already a TopoDS_Shape.
    if hasattr(raw, "IsNull"):
        try:
            if raw.IsNull():
                return None
        except Exception:
            pass
        return raw

    # Old API path: create_shape(...).geometry.brep_data contains ASCII BRep.
    brep_data = getattr(raw, "brep_data", None)
    if isinstance(brep_data, str) and brep_data.strip():
        return _read_brep_text_to_shape(brep_data)
    return None


def brep_from_ifc_element(ifc_geom_module, settings, element):
    """Materialize an OCCT shape for an IFC element via the BRep round-trip.

    Returns ``None`` on any failure so the caller can fall back gracefully.
    """
    _require_occt()
    try:
        # New IfcOpenShell versions can return a native TopoDS shape directly
        # (`use-python-opencascade`). Older versions expose `USE_BREP_DATA`.
        local_settings = ifc_geom_module.settings()
        _set_ifc_geom_setting(local_settings, "USE_WORLD_COORDS", True)
        _set_ifc_geom_setting(local_settings, "USE_PYTHON_OPENCASCADE", True)
        _set_ifc_geom_setting(local_settings, "USE_BREP_DATA", True)
        # Allow caller to override common knobs by passing a pre-built settings.
        if settings is not None:
            for key_name in ("USE_WORLD_COORDS", "USE_PYTHON_OPENCASCADE", "USE_BREP_DATA"):
                try:
                    source_key = getattr(settings, key_name)
                except Exception:
                    source_key = key_name.lower().replace("_", "-")
                try:
                    value = settings.get(source_key)
                except Exception:
                    continue
                _set_ifc_geom_setting(local_settings, key_name, value)

        shape_iter = ifc_geom_module.create_shape(local_settings, element)
        direct_shape = _coerce_occt_shape(shape_iter)
        if direct_shape is not None:
            return direct_shape
        return _coerce_occt_shape(getattr(shape_iter, "geometry", None))
    except Exception as exc:
        _LOG.debug("brep_from_ifc_element failed: %s", exc)
        return None


def section_shape(shape, face) -> List[object]:
    """Return canonical-sorted list of TopoDS_Edge from a planar section."""
    _require_occt()
    algo = BRepAlgoAPI_Section(shape, face, False)
    try:
        algo.ComputePCurveOn1(True)
    except Exception:  # pragma: no cover
        pass
    try:
        algo.Approximation(True)
    except Exception:  # pragma: no cover
        pass
    algo.Build()
    if not algo.IsDone():
        return []
    edges: List[object] = []
    explorer = TopExp_Explorer(algo.Shape(), TopAbs_EDGE)
    while explorer.More():
        edges.append(explorer.Current())
        explorer.Next()
    edges.sort(key=_edge_first_vertex_key)
    return edges


def _edge_first_vertex_key(edge) -> Tuple[float, float, float]:
    """Sort key for an edge: its first vertex coordinates, quantized."""
    explorer = TopExp_Explorer(edge, TopAbs_VERTEX)
    if not explorer.More():
        return (0.0, 0.0, 0.0)
    from OCC.Core.BRep import BRep_Tool  # local import — only reached when OCCT loaded
    vertex = explorer.Current()
    point = BRep_Tool.Pnt(vertex)
    return (quantize(point.X()), quantize(point.Y()), quantize(point.Z()))


def edge_to_polyline(edge, chord_tol_m: float) -> List[Tuple[float, float]]:
    """Sample a TopoDS_Edge to a quantized 2D polyline (XY projection)."""
    _require_occt()
    curve = BRepAdaptor_Curve(edge)
    sampler = GCPnts_QuasiUniformDeflection(curve, chord_tol_m)
    if not sampler.IsDone() or sampler.NbPoints() < 2:
        return []
    points: List[Tuple[float, float]] = []
    last: Optional[Tuple[float, float]] = None
    for i in range(1, sampler.NbPoints() + 1):
        pnt = sampler.Value(i)
        qp = quantize_point(pnt.X(), pnt.Y())
        if qp != last:
            points.append(qp)
            last = qp
    return points


def edge_to_polyline_3d(edge, chord_tol_m: float) -> List[Tuple[float, float, float]]:
    """Sample a TopoDS_Edge to a quantized 3D polyline.

    Unlike ``edge_to_polyline`` this returns ``(x, y, z)`` samples so callers
    can apply arbitrary planar projections (used by elevation views).
    """
    _require_occt()
    curve = BRepAdaptor_Curve(edge)
    sampler = GCPnts_QuasiUniformDeflection(curve, chord_tol_m)
    if not sampler.IsDone() or sampler.NbPoints() < 2:
        return []
    points: List[Tuple[float, float, float]] = []
    last: Optional[Tuple[float, float, float]] = None
    for i in range(1, sampler.NbPoints() + 1):
        pnt = sampler.Value(i)
        qp = (quantize(pnt.X()), quantize(pnt.Y()), quantize(pnt.Z()))
        if qp != last:
            points.append(qp)
            last = qp
    return points


def chain_polylines(segments: Sequence[Sequence[Tuple[float, float]]]) -> List[List[Tuple[float, float]]]:
    """Greedy endpoint chaining; deterministic on quantized + pre-sorted input."""
    remaining = [list(s) for s in segments if len(s) >= 2]
    chains: List[List[Tuple[float, float]]] = []
    while remaining:
        chain = remaining.pop(0)
        extended = True
        while extended:
            extended = False
            for idx in range(len(remaining)):
                seg = remaining[idx]
                if seg[0] == chain[-1]:
                    chain.extend(seg[1:])
                    remaining.pop(idx)
                    extended = True
                    break
                if seg[-1] == chain[-1]:
                    chain.extend(reversed(seg[:-1]))
                    remaining.pop(idx)
                    extended = True
                    break
                if seg[-1] == chain[0]:
                    chain = list(seg) + chain[1:]
                    remaining.pop(idx)
                    extended = True
                    break
                if seg[0] == chain[0]:
                    chain = list(reversed(seg))[:-1] + chain
                    remaining.pop(idx)
                    extended = True
                    break
        chains.append(chain)
    return chains


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------


def extract_cut_lines(
    ifc_geom_module,
    elements: Sequence[object],
    plane: CutPlane,
    per_element_budget_s: float,
    chord_tol_m: float,
    fallback: Optional[Callable[..., List[List[Tuple[float, float]]]]] = None,
    xy_extent_m: float = 250.0,
) -> List[TypedLine2D]:
    return extract_cut_lines_report(
        ifc_geom_module=ifc_geom_module,
        elements=elements,
        plane=plane,
        per_element_budget_s=per_element_budget_s,
        chord_tol_m=chord_tol_m,
        fallback=fallback,
        xy_extent_m=xy_extent_m,
    ).lines


def extract_cut_lines_report(
    ifc_geom_module,
    elements: Sequence[object],
    plane: CutPlane,
    per_element_budget_s: float,
    chord_tol_m: float,
    fallback: Optional[Callable[..., List[List[Tuple[float, float]]]]] = None,
    xy_extent_m: float = 250.0,
) -> CutExtractionReport:
    """Run OCCT section per element under a per-element wall-clock budget.

    ``fallback`` should return a list of 2D polylines (each a list of
    ``(x, y)`` points) when the OCCT path times out or raises.
    The callable may accept either ``fallback(element, plane_z)`` or
    ``fallback(element)`` for backwards compatibility.
    """
    _require_occt()
    cut_face = build_cut_face(plane, xy_extent_m)
    sorted_elements = sorted(
        elements,
        key=lambda el: (el.is_a(), getattr(el, "GlobalId", "") or "", el.id()),
    )
    results: List[TypedLine2D] = []
    fallback_events = 0
    fallback_timeout_events = 0
    fallback_exception_events = 0
    fallback_empty_events = 0
    fallback_line_count = 0
    fallback_by_class: Dict[str, int] = {}
    for element in sorted_elements:
        ifc_class = element.is_a()
        global_id = getattr(element, "GlobalId", "") or ""
        used_fallback = False
        try:
            polylines, notes = run_with_budget(
                lambda el=element: _section_one_element(
                    ifc_geom_module, el, cut_face, chord_tol_m
                ),
                per_element_budget_s,
            )
        except BudgetExceeded:
            used_fallback = True
            fallback_events += 1
            fallback_timeout_events += 1
            fallback_by_class[ifc_class] = fallback_by_class.get(ifc_class, 0) + 1
            polylines = _invoke_fallback(fallback, element, plane.z_m)
            notes = (
                f"OCCT section timed out after {per_element_budget_s:.1f}s; "
                "fell back to mesh slice.",
            )
        except Exception as exc:
            used_fallback = True
            fallback_events += 1
            fallback_exception_events += 1
            fallback_by_class[ifc_class] = fallback_by_class.get(ifc_class, 0) + 1
            polylines = _invoke_fallback(fallback, element, plane.z_m)
            notes = (f"OCCT section raised {type(exc).__name__}; fell back to mesh slice.",)

        if used_fallback and not polylines:
            fallback_empty_events += 1
        for polyline in polylines:
            if len(polyline) < 2:
                continue
            points = [Point2D(x=x, y=y) for (x, y) in polyline]
            if used_fallback:
                fallback_line_count += 1
            results.append(
                TypedLine2D(
                    kind=LineKind.CUT,
                    lineweight_class=LineweightClass.HEAVY,
                    points=points,
                    closed=polyline[0] == polyline[-1] and len(polyline) > 2,
                    source_element=global_id,
                    source_ifc_class=ifc_class,
                    notes=notes,
                )
            )

    return CutExtractionReport(
        lines=sort_lines_canonical(results),
        fallback_events=fallback_events,
        fallback_by_class=dict(sorted(fallback_by_class.items())),
        fallback_timeout_events=fallback_timeout_events,
        fallback_exception_events=fallback_exception_events,
        fallback_empty_events=fallback_empty_events,
        fallback_line_count=fallback_line_count,
    )


def _section_one_element(ifc_geom_module, element, cut_face, chord_tol_m):
    shape = brep_from_ifc_element(ifc_geom_module, None, element)
    if shape is None:
        return [], ()
    edges = section_shape(shape, cut_face)
    raw_segments = []
    for edge in edges:
        polyline = edge_to_polyline(edge, chord_tol_m)
        if len(polyline) >= 2:
            raw_segments.append(polyline)
    chains = chain_polylines(raw_segments)
    return chains, ()


def _invoke_fallback(
    fallback: Optional[Callable[..., List[List[Tuple[float, float]]]]],
    element,
    plane_z: float,
) -> List[List[Tuple[float, float]]]:
    if fallback is None:
        return []
    try:
        return fallback(element, plane_z)
    except TypeError:
        # Backwards compatibility with older fallback(element) callables.
        return fallback(element)
