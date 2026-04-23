from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class PageSpec:
    width_mm: float
    height_mm: float
    margin_mm: float
    title_block_height_mm: float


@dataclass(frozen=True)
class FloorPlanRule:
    cut_plane_m: float
    view_depth_below_m: float
    overhead_depth_above_m: float
    include_classes: List[str]


@dataclass(frozen=True)
class StyleProfile:
    profile_id: str
    region: str
    page: PageSpec
    lineweights_mm: Dict[str, float]
    floor_plan: FloorPlanRule
    sheet_prefix: str
    cover_sheet_id: str
    index_sheet_id: str


@dataclass(frozen=True)
class PreflightReport:
    input_path: str
    input_sha256: str
    size_bytes: int
    schema: str
    scanner: str
    entity_counts: Dict[str, int]
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class StoreySummary:
    index: int
    name: str
    elevation_m: Optional[float] = None


@dataclass(frozen=True)
class Bounds2D:
    min_x: float
    min_y: float
    max_x: float
    max_y: float


@dataclass(frozen=True)
class Point2D:
    x: float
    y: float


@dataclass(frozen=True)
class VectorPath:
    role: str
    points: List[Point2D]
    closed: bool = False
    ifc_class: Optional[str] = None


@dataclass(frozen=True)
class VectorPolygon:
    role: str
    rings: List[List[Point2D]]


@dataclass(frozen=True)
class NormalizedModel:
    model_hash: str
    project_name: str
    building_name: str
    schema: str
    source_scanner: str
    storeys: List[StoreySummary]
    space_count: int
    supported_class_counts: Dict[str, int]
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PlannedView:
    view_id: str
    sheet_id: str
    title: str
    storey_name: str
    storey_elevation_m: Optional[float]
    cut_plane_m: float
    view_depth_below_m: float
    overhead_depth_above_m: float
    included_classes: List[str]


@dataclass(frozen=True)
class GeometrySummary:
    view_id: str
    backend: str
    cut_candidates: Dict[str, int]
    projection_candidates: Dict[str, int]
    source_elements: int = 0
    path_count: int = 0
    bounds: Optional[Bounds2D] = None
    paths: List[VectorPath] = field(default_factory=list, metadata={"serialize": False})
    polygons: List[VectorPolygon] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScheduleRow:
    ifc_class: str
    label: str
    storey_name: str
    count: int


@dataclass(frozen=True)
class ScheduleSheet:
    schedule_id: str
    sheet_id: str
    title: str
    category: str
    label_header: str
    rows: List[ScheduleRow]
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SheetArtifact:
    sheet_id: str
    title: str
    svg_path: str
    page_number: int
    role: str


@dataclass(frozen=True)
class PipelineManifest:
    job_id: str
    input_sha256: str
    style_profile_id: str
    model_hash: str
    output_dir: str
    pdf_path: str
    sheets: List[SheetArtifact]
    warnings: List[str] = field(default_factory=list)


def to_primitive(value):
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {
            field_info.name: to_primitive(getattr(value, field_info.name))
            for field_info in fields(value)
            if field_info.metadata.get("serialize", True)
        }
    if isinstance(value, dict):
        return {str(k): to_primitive(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_primitive(v) for v in value]
    if isinstance(value, tuple):
        return [to_primitive(v) for v in value]
    return value


def optional_name(value: Optional[str], default: str) -> str:
    if value is None:
        return default
    stripped = value.strip()
    return stripped if stripped else default
