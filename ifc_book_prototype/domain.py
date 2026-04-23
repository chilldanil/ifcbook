from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class PageSpec:
    width_mm: float
    height_mm: float
    margin_mm: float
    title_block_height_mm: float


@dataclass(frozen=True)
class FeatureOverlayRule:
    enabled: bool = True
    show_legend: bool = True
    leader_enabled: bool = True
    doors_enabled: bool = True
    stairs_enabled: bool = True
    rooms_enabled: bool = True
    max_door_markers: int = 120
    max_stair_arrows: int = 60
    max_room_tags: int = 80
    door_color: str = "#1d4ed8"
    stair_color: str = "#0f766e"
    room_fill_color: str = "#ffffff"
    room_stroke_color: str = "#b45309"
    room_text_color: str = "#92400e"
    legend_color: str = "#334155"
    leader_color: str = "#94a3b8"
    leader_stroke_width: float = 0.16
    leader_dasharray: str = "0.7 0.7"
    door_label: str = "D"
    stair_label: str = "UP"
    room_label_mode: str = "sequential"
    room_label_prefix: str = "R"
    room_label_start: int = 1
    room_fixed_label: str = "ROOM"


@dataclass(frozen=True)
class FloorPlanRule:
    cut_plane_m: float
    view_depth_below_m: float
    overhead_depth_above_m: float
    include_classes: List[str]
    # --- Phase 2 OCCT cut-extractor knobs (defaults are backwards compatible) ---
    cut_classes: List[str] = field(default_factory=lambda: ["IfcWall", "IfcSlab", "IfcColumn", "IfcBeam", "IfcMember"])
    occt_per_element_budget_s: float = 2.0
    cut_chord_tolerance_m: float = 5.0e-4
    highlight_fallback_lines: bool = False
    # --- Phase 3C owned projection/hidden toggles (default off = back-compat) ---
    own_projection: bool = False
    own_hidden: bool = False
    feature_overlay: FeatureOverlayRule = field(default_factory=FeatureOverlayRule)


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


VIEW_KIND_PLAN = "plan"
VIEW_KIND_ELEVATION_NORTH = "elevation_north"
VIEW_KIND_ELEVATION_SOUTH = "elevation_south"
VIEW_KIND_ELEVATION_EAST = "elevation_east"
VIEW_KIND_ELEVATION_WEST = "elevation_west"

ELEVATION_VIEW_KINDS = (
    VIEW_KIND_ELEVATION_NORTH,
    VIEW_KIND_ELEVATION_SOUTH,
    VIEW_KIND_ELEVATION_EAST,
    VIEW_KIND_ELEVATION_WEST,
)


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
    # Back-compat default: existing serialized view manifests load as plans.
    view_kind: str = VIEW_KIND_PLAN


class LineKind(Enum):
    CUT = "CUT"
    PROJECTED = "PROJECTED"
    HIDDEN = "HIDDEN"
    OUTLINE = "OUTLINE"


class LineweightClass(Enum):
    HEAVY = "HEAVY"
    MEDIUM = "MEDIUM"
    LIGHT = "LIGHT"
    FINE = "FINE"


@dataclass(frozen=True)
class TypedLine2D:
    kind: LineKind
    lineweight_class: LineweightClass
    points: List[Point2D]
    closed: bool = False
    source_element: Optional[str] = None
    source_ifc_class: Optional[str] = None
    z_order_hint: int = 0
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TypedRegion2D:
    kind: LineKind
    rings: List[List[Point2D]]
    source_element: Optional[str] = None
    source_ifc_class: Optional[str] = None


@dataclass(frozen=True)
class ViewLinework:
    lines: List[TypedLine2D] = field(default_factory=list, metadata={"serialize": False})
    regions: List[TypedRegion2D] = field(default_factory=list, metadata={"serialize": False})
    quantization_m: float = 1.0e-5
    counts_by_kind: Dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureAnchor2D:
    ifc_class: str
    anchor: Point2D
    dir_x: float = 1.0
    dir_y: float = 0.0
    source_element: Optional[str] = None
    label: Optional[str] = None


def typed_line_sort_key(line: TypedLine2D):
    first_x = line.points[0].x if line.points else 0.0
    first_y = line.points[0].y if line.points else 0.0
    return (
        line.kind.name,
        line.source_ifc_class or "",
        line.source_element or "",
        first_x,
        first_y,
        len(line.points),
    )


def typed_region_sort_key(region: TypedRegion2D):
    first_ring = region.rings[0] if region.rings else []
    first_x = first_ring[0].x if first_ring else 0.0
    first_y = first_ring[0].y if first_ring else 0.0
    return (
        region.kind.name,
        region.source_ifc_class or "",
        region.source_element or "",
        first_x,
        first_y,
        len(region.rings),
    )


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
    linework: Optional[ViewLinework] = field(default=None, metadata={"serialize": False})
    linework_counts: Dict[str, int] = field(default_factory=dict)
    feature_anchors: List[FeatureAnchor2D] = field(default_factory=list)
    feature_anchor_counts: Dict[str, int] = field(default_factory=dict)
    fallback_events: int = 0
    fallback_by_class: Dict[str, int] = field(default_factory=dict)
    fallback_timeout_events: int = 0
    fallback_exception_events: int = 0
    fallback_empty_events: int = 0


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
    if isinstance(value, Enum):
        return value.name
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
