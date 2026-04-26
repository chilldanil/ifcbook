from __future__ import annotations

import argparse
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import benchmark as benchmark_module
from .cli import run_pipeline_job
from .domain import PipelineManifest
from .runtime_gate import (
    RuntimeGateThresholds,
    evaluate_runtime_gate_from_run_dir,
    format_runtime_gate_human,
    format_runtime_gate_machine,
)

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except Exception as exc:  # pragma: no cover - depends on host Tcl/Tk install.
    raise RuntimeError("Tkinter is required to run the desktop UI.") from exc


@dataclass(frozen=True)
class UiDefaults:
    mode: str
    ifc_path: str
    bundle_dir: str
    output_dir: str
    profile_path: str


@dataclass(frozen=True)
class RunRequest:
    mode: str
    output_dir: Path
    ifc_path: Path | None
    bundle_dir: Path | None
    profile_path: str | None


@dataclass(frozen=True)
class RuntimeGateRequest:
    run_dir: Path
    thresholds: RuntimeGateThresholds


@dataclass(frozen=True)
class BenchmarkRequest:
    out_root: Path
    json_out: Path
    md_out: Path


def _normalized_optional(raw: str) -> str | None:
    stripped = raw.strip()
    return stripped if stripped else None


def _parse_optional_float(raw: str, *, field_name: str) -> float | None:
    value = _normalized_optional(raw)
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a number.") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite.")
    return parsed


def _parse_optional_int(raw: str, *, field_name: str) -> int | None:
    value = _normalized_optional(raw)
    if value is None:
        return None
    try:
        return int(value, 10)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc


def parse_runtime_gate_thresholds(
    *,
    max_fallback_event_rate: str,
    max_timeout_events_total: str,
    min_occt_coverage_rate: str,
    min_hidden_lines_total: str,
    min_hidden_line_ratio: str,
) -> RuntimeGateThresholds:
    thresholds = RuntimeGateThresholds(
        max_fallback_event_rate=_parse_optional_float(
            max_fallback_event_rate,
            field_name="max_fallback_event_rate",
        ),
        max_timeout_events_total=_parse_optional_int(
            max_timeout_events_total,
            field_name="max_timeout_events_total",
        ),
        min_occt_coverage_rate=_parse_optional_float(
            min_occt_coverage_rate,
            field_name="min_occt_coverage_rate",
        ),
        min_hidden_lines_total=_parse_optional_int(
            min_hidden_lines_total,
            field_name="min_hidden_lines_total",
        ),
        min_hidden_line_ratio=_parse_optional_float(
            min_hidden_line_ratio,
            field_name="min_hidden_line_ratio",
        ),
    )
    thresholds.validate()
    return thresholds


def build_runtime_gate_request(
    *,
    last_output_dir: Path | None,
    max_fallback_event_rate: str,
    max_timeout_events_total: str,
    min_occt_coverage_rate: str,
    min_hidden_lines_total: str,
    min_hidden_line_ratio: str,
) -> RuntimeGateRequest:
    if last_output_dir is None:
        raise ValueError("Runtime gate is available after a successful pipeline run.")
    run_dir = last_output_dir.expanduser().resolve()
    if not run_dir.exists():
        raise ValueError(f"Run output directory does not exist: {run_dir}")
    if not run_dir.is_dir():
        raise ValueError(f"Run output path is not a directory: {run_dir}")

    thresholds = parse_runtime_gate_thresholds(
        max_fallback_event_rate=max_fallback_event_rate,
        max_timeout_events_total=max_timeout_events_total,
        min_occt_coverage_rate=min_occt_coverage_rate,
        min_hidden_lines_total=min_hidden_lines_total,
        min_hidden_line_ratio=min_hidden_line_ratio,
    )
    if not thresholds.has_any_limit():
        raise ValueError("Set at least one runtime gate threshold.")
    return RuntimeGateRequest(run_dir=run_dir, thresholds=thresholds)


def normalize_benchmark_root(raw: str) -> Path:
    root_raw = _normalized_optional(raw)
    if root_raw is None:
        raise ValueError("Benchmark root directory is required.")
    root = Path(root_raw).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"Benchmark root directory does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Benchmark root path is not a directory: {root}")
    return root


def build_benchmark_request(*, benchmark_root: str) -> BenchmarkRequest:
    out_root = normalize_benchmark_root(benchmark_root)
    return BenchmarkRequest(
        out_root=out_root,
        json_out=out_root / "benchmark_summary.json",
        md_out=out_root / "benchmark_summary.md",
    )


def _default_benchmark_root(output_dir: str) -> str:
    output_raw = _normalized_optional(output_dir)
    if output_raw is None:
        return str((Path.cwd() / "out").resolve())
    return str(Path(output_raw).expanduser().resolve().parent)


def build_run_request(
    *,
    mode: str,
    ifc_path: str,
    bundle_dir: str,
    output_dir: str,
    profile_path: str,
) -> RunRequest:
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"ifc", "bundle"}:
        raise ValueError("Mode must be either 'ifc' or 'bundle'.")

    output_raw = _normalized_optional(output_dir)
    if output_raw is None:
        raise ValueError("Output directory is required.")
    output_path = Path(output_raw).expanduser().resolve()

    profile_raw = _normalized_optional(profile_path)
    if profile_raw is not None and not Path(profile_raw).expanduser().exists():
        raise ValueError(f"Profile file does not exist: {profile_raw}")

    if normalized_mode == "ifc":
        ifc_raw = _normalized_optional(ifc_path)
        if ifc_raw is None:
            raise ValueError("IFC file path is required in IFC mode.")
        ifc_value = Path(ifc_raw).expanduser()
        if not ifc_value.exists():
            raise ValueError(f"IFC file does not exist: {ifc_value}")
        return RunRequest(
            mode=normalized_mode,
            output_dir=output_path,
            ifc_path=ifc_value,
            bundle_dir=None,
            profile_path=profile_raw,
        )

    bundle_raw = _normalized_optional(bundle_dir)
    if bundle_raw is None:
        raise ValueError("Bundle directory is required in bundle mode.")
    bundle_value = Path(bundle_raw).expanduser()
    if not bundle_value.exists():
        raise ValueError(f"Bundle directory does not exist: {bundle_value}")
    return RunRequest(
        mode=normalized_mode,
        output_dir=output_path,
        ifc_path=None,
        bundle_dir=bundle_value,
        profile_path=profile_raw,
    )


def format_manifest_summary(manifest: PipelineManifest) -> str:
    lines = [
        f"job_id={manifest.job_id}",
        f"output_dir={manifest.output_dir}",
        f"pdf={manifest.pdf_path or '(not produced)'}",
        "sheets:",
    ]
    for sheet in manifest.sheets:
        lines.append(f"  {sheet.sheet_id} -> {sheet.svg_path}")
    if manifest.warnings:
        lines.append("warnings:")
        for warning in manifest.warnings:
            lines.append(f"  - {warning}")
    return "\n".join(lines)


def _format_runtime_summary(output_dir: Path) -> str | None:
    summary_path = output_dir / "metadata" / "geometry_runtime_summary.json"
    if not summary_path.exists():
        return None
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    backend_counts = data.get("backend_counts", {}) or {}
    fallback = data.get("fallback", {}) or {}
    lines = [
        "runtime_summary:",
        f"  view_count={data.get('view_count', 0)}",
        f"  occt_view_count={data.get('occt_view_count', 0)}",
        "  backend_counts:",
    ]
    if backend_counts:
        for name, count in sorted(backend_counts.items()):
            lines.append(f"    {name}: {count}")
    else:
        lines.append("    (none)")
    lines.extend(
        [
            f"  fallback.events_total={fallback.get('events_total', 0)}",
            f"  fallback.timeout_events={fallback.get('timeout_events', 0)}",
            f"  fallback.exception_events={fallback.get('exception_events', 0)}",
            f"  fallback.empty_events={fallback.get('empty_events', 0)}",
        ]
    )
    return "\n".join(lines)


def _open_path(path: Path) -> None:
    if sys.platform.startswith("darwin"):
        subprocess.run(["open", str(path)], check=False)
        return
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    subprocess.run(["xdg-open", str(path)], check=False)


class PipelineUiApp(tk.Tk):
    def __init__(self, defaults: UiDefaults):
        super().__init__()
        self.title("IFC Book Prototype UI")
        self.geometry("1100x760")
        self.minsize(900, 620)

        self.mode_var = tk.StringVar(value=defaults.mode)
        self.ifc_var = tk.StringVar(value=defaults.ifc_path)
        self.bundle_var = tk.StringVar(value=defaults.bundle_dir)
        self.output_var = tk.StringVar(value=defaults.output_dir)
        self.profile_var = tk.StringVar(value=defaults.profile_path)
        self.max_fallback_event_rate_var = tk.StringVar(value="")
        self.max_timeout_events_total_var = tk.StringVar(value="")
        self.min_occt_coverage_rate_var = tk.StringVar(value="")
        self.min_hidden_lines_total_var = tk.StringVar(value="")
        self.min_hidden_line_ratio_var = tk.StringVar(value="")
        self.benchmark_root_var = tk.StringVar(value=_default_benchmark_root(defaults.output_dir))
        self.status_var = tk.StringVar(value="Ready.")

        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._last_output_dir: Path | None = None
        self._last_pdf_path: Path | None = None

        self._build_layout()
        self._sync_mode_controls()
        self.after(120, self._poll_events)

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        container = ttk.Frame(self, padding=14)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        input_frame = ttk.LabelFrame(container, text="Inputs", padding=10)
        input_frame.grid(row=0, column=0, sticky="ew")
        input_frame.columnconfigure(1, weight=1)

        mode_row = ttk.Frame(input_frame)
        mode_row.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(mode_row, text="Mode:").pack(side="left")
        ttk.Radiobutton(
            mode_row,
            text="IFC model",
            value="ifc",
            variable=self.mode_var,
            command=self._sync_mode_controls,
        ).pack(side="left", padx=(8, 0))
        ttk.Radiobutton(
            mode_row,
            text="Bundle replay",
            value="bundle",
            variable=self.mode_var,
            command=self._sync_mode_controls,
        ).pack(side="left", padx=(12, 0))

        ttk.Label(input_frame, text="IFC file").grid(row=1, column=0, sticky="w")
        self.ifc_entry = ttk.Entry(input_frame, textvariable=self.ifc_var)
        self.ifc_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=3)
        self.ifc_browse_button = ttk.Button(input_frame, text="Browse", command=self._pick_ifc_file)
        self.ifc_browse_button.grid(row=1, column=2, sticky="e")

        ttk.Label(input_frame, text="Bundle dir").grid(row=2, column=0, sticky="w")
        self.bundle_entry = ttk.Entry(input_frame, textvariable=self.bundle_var)
        self.bundle_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=3)
        self.bundle_browse_button = ttk.Button(
            input_frame,
            text="Browse",
            command=self._pick_bundle_dir,
        )
        self.bundle_browse_button.grid(row=2, column=2, sticky="e")

        options_frame = ttk.LabelFrame(container, text="Options", padding=10)
        options_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        options_frame.columnconfigure(1, weight=1)

        ttk.Label(options_frame, text="Output dir").grid(row=0, column=0, sticky="w")
        self.output_entry = ttk.Entry(options_frame, textvariable=self.output_var)
        self.output_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=3)
        self.output_browse_button = ttk.Button(
            options_frame,
            text="Browse",
            command=self._pick_output_dir,
        )
        self.output_browse_button.grid(row=0, column=2, sticky="e")

        ttk.Label(options_frame, text="Profile JSON (optional)").grid(row=1, column=0, sticky="w")
        self.profile_entry = ttk.Entry(options_frame, textvariable=self.profile_var)
        self.profile_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=3)
        self.profile_browse_button = ttk.Button(
            options_frame,
            text="Browse",
            command=self._pick_profile_file,
        )
        self.profile_browse_button.grid(row=1, column=2, sticky="e")

        ttk.Label(options_frame, text="max_fallback_event_rate").grid(row=2, column=0, sticky="w")
        self.max_fallback_event_rate_entry = ttk.Entry(
            options_frame,
            textvariable=self.max_fallback_event_rate_var,
        )
        self.max_fallback_event_rate_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=3)

        ttk.Label(options_frame, text="max_timeout_events_total").grid(row=3, column=0, sticky="w")
        self.max_timeout_events_total_entry = ttk.Entry(
            options_frame,
            textvariable=self.max_timeout_events_total_var,
        )
        self.max_timeout_events_total_entry.grid(row=3, column=1, sticky="ew", padx=8, pady=3)

        ttk.Label(options_frame, text="min_occt_coverage_rate").grid(row=4, column=0, sticky="w")
        self.min_occt_coverage_rate_entry = ttk.Entry(
            options_frame,
            textvariable=self.min_occt_coverage_rate_var,
        )
        self.min_occt_coverage_rate_entry.grid(row=4, column=1, sticky="ew", padx=8, pady=3)

        ttk.Label(options_frame, text="min_hidden_lines_total").grid(row=5, column=0, sticky="w")
        self.min_hidden_lines_total_entry = ttk.Entry(
            options_frame,
            textvariable=self.min_hidden_lines_total_var,
        )
        self.min_hidden_lines_total_entry.grid(row=5, column=1, sticky="ew", padx=8, pady=3)

        ttk.Label(options_frame, text="min_hidden_line_ratio").grid(row=6, column=0, sticky="w")
        self.min_hidden_line_ratio_entry = ttk.Entry(
            options_frame,
            textvariable=self.min_hidden_line_ratio_var,
        )
        self.min_hidden_line_ratio_entry.grid(row=6, column=1, sticky="ew", padx=8, pady=3)

        ttk.Label(options_frame, text="Benchmark root").grid(row=7, column=0, sticky="w")
        self.benchmark_root_entry = ttk.Entry(options_frame, textvariable=self.benchmark_root_var)
        self.benchmark_root_entry.grid(row=7, column=1, sticky="ew", padx=8, pady=3)
        self.benchmark_root_browse_button = ttk.Button(
            options_frame,
            text="Browse",
            command=self._pick_benchmark_root,
        )
        self.benchmark_root_browse_button.grid(row=7, column=2, sticky="e")

        action_row = ttk.Frame(container)
        action_row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.run_button = ttk.Button(action_row, text="Run Pipeline", command=self._start_run)
        self.run_button.pack(side="left")
        self.runtime_gate_button = ttk.Button(
            action_row,
            text="Run Runtime Gate",
            command=self._start_runtime_gate,
        )
        self.runtime_gate_button.pack(side="left", padx=8)
        self.benchmark_button = ttk.Button(
            action_row,
            text="Run Benchmark Summary",
            command=self._start_benchmark_summary,
        )
        self.benchmark_button.pack(side="left")
        self.open_output_button = ttk.Button(
            action_row,
            text="Open Output Folder",
            command=self._open_output_folder,
        )
        self.open_output_button.pack(side="left", padx=(8, 0))
        self.open_pdf_button = ttk.Button(action_row, text="Open PDF", command=self._open_pdf)
        self.open_pdf_button.pack(side="left", padx=(8, 0))
        self.progress = ttk.Progressbar(action_row, mode="indeterminate", length=220)
        self.progress.pack(side="right")

        log_frame = ttk.LabelFrame(container, text="Run Log", padding=10)
        log_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_widget = scrolledtext.ScrolledText(
            log_frame,
            state="disabled",
            wrap="word",
            height=24,
            font=("Menlo", 12),
        )
        self.log_widget.grid(row=0, column=0, sticky="nsew")

        status_row = ttk.Frame(container)
        status_row.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(status_row, textvariable=self.status_var).pack(side="left")

        self.open_output_button.state(["disabled"])
        self.open_pdf_button.state(["disabled"])
        self.runtime_gate_button.state(["disabled"])

    def _sync_mode_controls(self) -> None:
        mode = self.mode_var.get().strip().lower()
        if mode == "bundle":
            self.ifc_entry.state(["disabled"])
            self.ifc_browse_button.state(["disabled"])
            self.bundle_entry.state(["!disabled"])
            self.bundle_browse_button.state(["!disabled"])
            return
        self.ifc_entry.state(["!disabled"])
        self.ifc_browse_button.state(["!disabled"])
        self.bundle_entry.state(["disabled"])
        self.bundle_browse_button.state(["disabled"])

    def _set_running(self, running: bool) -> None:
        if running:
            self.run_button.state(["disabled"])
            self.runtime_gate_button.state(["disabled"])
            self.benchmark_button.state(["disabled"])
            self.open_output_button.state(["disabled"])
            self.open_pdf_button.state(["disabled"])
            self.progress.start(10)
            return
        self.run_button.state(["!disabled"])
        self.benchmark_button.state(["!disabled"])
        self.progress.stop()
        if self._last_output_dir is not None:
            self.runtime_gate_button.state(["!disabled"])
            self.open_output_button.state(["!disabled"])
        else:
            self.runtime_gate_button.state(["disabled"])
        if self._last_pdf_path is not None and self._last_pdf_path.exists():
            self.open_pdf_button.state(["!disabled"])

    def _append_log(self, text: str) -> None:
        self.log_widget.config(state="normal")
        self.log_widget.insert("end", text.rstrip() + "\n")
        self.log_widget.see("end")
        self.log_widget.config(state="disabled")

    def _clear_log(self) -> None:
        self.log_widget.config(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.config(state="disabled")

    def _pick_ifc_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select IFC model file",
            filetypes=[
                ("IFC model", "*.ifc *.ifczip"),
                ("All files", "*.*"),
            ],
        )
        if selected:
            self.ifc_var.set(selected)

    def _pick_bundle_dir(self) -> None:
        selected = filedialog.askdirectory(title="Select existing bundle directory")
        if selected:
            self.bundle_var.set(selected)

    def _pick_output_dir(self) -> None:
        selected = filedialog.askdirectory(title="Select output directory")
        if selected:
            self.output_var.set(selected)

    def _pick_profile_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select style profile JSON",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if selected:
            self.profile_var.set(selected)

    def _pick_benchmark_root(self) -> None:
        selected = filedialog.askdirectory(title="Select benchmark root directory")
        if selected:
            self.benchmark_root_var.set(selected)

    def _start_run(self) -> None:
        try:
            request = build_run_request(
                mode=self.mode_var.get(),
                ifc_path=self.ifc_var.get(),
                bundle_dir=self.bundle_var.get(),
                output_dir=self.output_var.get(),
                profile_path=self.profile_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        self._last_output_dir = None
        self._last_pdf_path = None
        self._clear_log()
        self._append_log(f"Starting run in {request.mode} mode...")
        self.status_var.set("Running...")
        self._set_running(True)
        self._worker = threading.Thread(target=self._run_worker, args=(request,), daemon=True)
        self._worker.start()

    def _start_runtime_gate(self) -> None:
        try:
            request = build_runtime_gate_request(
                last_output_dir=self._last_output_dir,
                max_fallback_event_rate=self.max_fallback_event_rate_var.get(),
                max_timeout_events_total=self.max_timeout_events_total_var.get(),
                min_occt_coverage_rate=self.min_occt_coverage_rate_var.get(),
                min_hidden_lines_total=self.min_hidden_lines_total_var.get(),
                min_hidden_line_ratio=self.min_hidden_line_ratio_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Invalid runtime gate options", str(exc))
            return

        self._append_log(f"Running runtime gate on {request.run_dir}...")
        self.status_var.set("Running runtime gate...")
        self._set_running(True)
        self._worker = threading.Thread(target=self._runtime_gate_worker, args=(request,), daemon=True)
        self._worker.start()

    def _start_benchmark_summary(self) -> None:
        try:
            request = build_benchmark_request(benchmark_root=self.benchmark_root_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid benchmark options", str(exc))
            return

        self._append_log(f"Running benchmark summary in {request.out_root}...")
        self.status_var.set("Running benchmark summary...")
        self._set_running(True)
        self._worker = threading.Thread(target=self._benchmark_worker, args=(request,), daemon=True)
        self._worker.start()

    def _run_worker(self, request: RunRequest) -> None:
        started = time.monotonic()
        try:
            manifest = run_pipeline_job(
                output_dir=request.output_dir,
                profile_path=request.profile_path,
                ifc_path=request.ifc_path,
                bundle_dir=request.bundle_dir,
            )
            self._events.put(("success", manifest, time.monotonic() - started))
        except Exception:
            self._events.put(("error", traceback.format_exc(), time.monotonic() - started))

    def _runtime_gate_worker(self, request: RuntimeGateRequest) -> None:
        started = time.monotonic()
        try:
            result = evaluate_runtime_gate_from_run_dir(
                request.run_dir,
                thresholds=request.thresholds,
            )
            human = format_runtime_gate_human(result)
            machine = format_runtime_gate_machine(result)
            gate_out = request.run_dir / benchmark_module.RUNTIME_GATE_RELATIVE
            gate_out.parent.mkdir(parents=True, exist_ok=True)
            gate_out.write_text(
                json.dumps(result.as_dict(), indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            self._events.put(
                (
                    "runtime_gate_success",
                    human,
                    machine,
                    gate_out,
                    result.passed,
                    time.monotonic() - started,
                )
            )
        except Exception:
            self._events.put(("runtime_gate_error", traceback.format_exc(), time.monotonic() - started))

    def _benchmark_worker(self, request: BenchmarkRequest) -> None:
        started = time.monotonic()
        try:
            run_dirs = benchmark_module.discover_run_dirs(request.out_root)
            if not run_dirs:
                raise ValueError(
                    f"No run directories with {benchmark_module.RUNTIME_SUMMARY_RELATIVE} under {request.out_root}"
                )
            samples = [benchmark_module.load_sample_benchmark(run_dir) for run_dir in run_dirs]
            summary = benchmark_module.build_benchmark_summary(samples)
            request.json_out.parent.mkdir(parents=True, exist_ok=True)
            request.md_out.parent.mkdir(parents=True, exist_ok=True)
            request.json_out.write_text(
                json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            request.md_out.write_text(
                benchmark_module.format_benchmark_markdown(summary),
                encoding="utf-8",
            )
            gate = summary.get("gate", {})
            fail_count = 0
            if isinstance(gate, dict):
                fail_count = int(gate.get("fail_count", 0))
            sample_count = int(summary.get("sample_count", 0))
            self._events.put(
                (
                    "benchmark_success",
                    request.json_out,
                    request.md_out,
                    sample_count,
                    fail_count,
                    time.monotonic() - started,
                )
            )
        except Exception:
            self._events.put(("benchmark_error", traceback.format_exc(), time.monotonic() - started))

    def _poll_events(self) -> None:
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            event_type = event[0]
            if event_type == "success":
                manifest = event[1]
                duration_s = float(event[2])
                self._on_success(manifest=manifest, duration_s=duration_s)
                continue
            if event_type == "error":
                error_text = str(event[1])
                duration_s = float(event[2])
                self._on_error(error_text=error_text, duration_s=duration_s)
                continue
            if event_type == "runtime_gate_success":
                self._on_runtime_gate_success(
                    human_text=str(event[1]),
                    machine_text=str(event[2]),
                    gate_out=Path(event[3]),
                    passed=bool(event[4]),
                    duration_s=float(event[5]),
                )
                continue
            if event_type == "runtime_gate_error":
                self._on_runtime_gate_error(
                    error_text=str(event[1]),
                    duration_s=float(event[2]),
                )
                continue
            if event_type == "benchmark_success":
                self._on_benchmark_success(
                    json_out=Path(event[1]),
                    md_out=Path(event[2]),
                    sample_count=int(event[3]),
                    fail_count=int(event[4]),
                    duration_s=float(event[5]),
                )
                continue
            if event_type == "benchmark_error":
                self._on_benchmark_error(
                    error_text=str(event[1]),
                    duration_s=float(event[2]),
                )
                continue
        self.after(120, self._poll_events)

    def _on_success(self, *, manifest: PipelineManifest, duration_s: float) -> None:
        self._last_output_dir = Path(manifest.output_dir)
        self._last_pdf_path = Path(manifest.pdf_path) if manifest.pdf_path else None
        self._append_log(format_manifest_summary(manifest))
        runtime_summary = _format_runtime_summary(self._last_output_dir)
        if runtime_summary:
            self._append_log(runtime_summary)
        self.status_var.set(f"Completed in {duration_s:.1f}s.")
        self._set_running(False)

    def _on_error(self, *, error_text: str, duration_s: float) -> None:
        self._append_log("Pipeline failed:")
        self._append_log(error_text)
        self.status_var.set(f"Failed after {duration_s:.1f}s.")
        self._set_running(False)
        messagebox.showerror("Pipeline failed", "See the run log for the full traceback.")

    def _on_runtime_gate_success(
        self,
        *,
        human_text: str,
        machine_text: str,
        gate_out: Path,
        passed: bool,
        duration_s: float,
    ) -> None:
        self._append_log(human_text)
        self._append_log(f"RUNTIME_GATE_JSON={machine_text}")
        self._append_log(f"runtime_gate_result={gate_out}")
        status = "passed" if passed else "failed"
        self.status_var.set(f"Runtime gate {status} in {duration_s:.1f}s.")
        self._set_running(False)

    def _on_runtime_gate_error(self, *, error_text: str, duration_s: float) -> None:
        self._append_log("Runtime gate failed:")
        self._append_log(error_text)
        self.status_var.set(f"Runtime gate failed after {duration_s:.1f}s.")
        self._set_running(False)
        messagebox.showerror("Runtime gate failed", "See the run log for the full traceback.")

    def _on_benchmark_success(
        self,
        *,
        json_out: Path,
        md_out: Path,
        sample_count: int,
        fail_count: int,
        duration_s: float,
    ) -> None:
        self._append_log(
            f"benchmark_summary: sample_count={sample_count} gate_fail_count={fail_count}"
        )
        self._append_log(f"json={json_out}")
        self._append_log(f"md={md_out}")
        self.status_var.set(f"Benchmark summary completed in {duration_s:.1f}s.")
        self._set_running(False)

    def _on_benchmark_error(self, *, error_text: str, duration_s: float) -> None:
        self._append_log("Benchmark summary failed:")
        self._append_log(error_text)
        self.status_var.set(f"Benchmark summary failed after {duration_s:.1f}s.")
        self._set_running(False)
        messagebox.showerror("Benchmark summary failed", "See the run log for the full traceback.")

    def _open_output_folder(self) -> None:
        if self._last_output_dir is None:
            return
        _open_path(self._last_output_dir)

    def _open_pdf(self) -> None:
        if self._last_pdf_path is None:
            return
        _open_path(self._last_pdf_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Desktop UI for IFC Book Prototype")
    parser.add_argument("--ifc", help="Prefill IFC file path")
    parser.add_argument("--bundle", help="Prefill bundle directory path")
    parser.add_argument("--out", help="Prefill output directory path")
    parser.add_argument("--profile", help="Prefill optional style profile JSON path")
    return parser


def _build_defaults(args: argparse.Namespace) -> UiDefaults:
    if args.ifc and args.bundle:
        raise ValueError("Specify either --ifc or --bundle, not both.")

    default_output_dir = str((Path.cwd() / "out" / "ui_run").resolve())
    mode = "bundle" if args.bundle else "ifc"
    return UiDefaults(
        mode=mode,
        ifc_path=args.ifc or "",
        bundle_dir=args.bundle or "",
        output_dir=args.out or default_output_dir,
        profile_path=args.profile or "",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        defaults = _build_defaults(args)
    except ValueError as exc:
        parser.error(str(exc))

    app = PipelineUiApp(defaults=defaults)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
