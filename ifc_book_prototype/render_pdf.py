from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
from xml.etree import ElementTree


MM_TO_PT = 72.0 / 25.4
SVG_NS = "http://www.w3.org/2000/svg"
PATH_TOKEN_RE = re.compile(r"[MLHVZmlhvz]|-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def write_pdf_from_svg_sheets(path: Path, svg_paths: Iterable[Path]) -> None:
    pages = [_parse_svg_sheet(svg_path) for svg_path in svg_paths]
    if not pages:
        raise ValueError("At least one SVG sheet is required.")

    object_count = 2 * len(pages) + 5
    font_regular_id = 1
    font_bold_id = 2
    pages_object_id = 3
    catalog_object_id = object_count - 1
    info_object_id = object_count

    objects: List[str] = [""] * object_count
    objects[font_regular_id - 1] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects[font_bold_id - 1] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"

    kid_refs: List[str] = []
    for index, (width_mm, height_mm, stream) in enumerate(pages):
        page_object_id = 4 + index * 2
        content_object_id = page_object_id + 1
        kid_refs.append(f"{page_object_id} 0 R")

        width_pt = width_mm * MM_TO_PT
        height_pt = height_mm * MM_TO_PT
        objects[content_object_id - 1] = (
            f"<< /Length {len(stream.encode('utf-8'))} >>\n"
            f"stream\n{stream}\nendstream"
        )
        objects[page_object_id - 1] = (
            f"<< /Type /Page /Parent {pages_object_id} 0 R "
            f"/MediaBox [0 0 {width_pt:.2f} {height_pt:.2f}] "
            f"/Resources << /Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R >> >> "
            f"/Contents {content_object_id} 0 R >>"
        )

    objects[pages_object_id - 1] = (
        f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(kid_refs)}] >>"
    )
    objects[catalog_object_id - 1] = f"<< /Type /Catalog /Pages {pages_object_id} 0 R >>"
    objects[info_object_id - 1] = (
        "<< /Producer (ifc-book-prototype) "
        "/Creator (ifc-book-prototype) "
        "/Title (Prototype Drawing Book) "
        "/CreationDate (D:20260101000000Z) "
        "/ModDate (D:20260101000000Z) >>"
    )

    output = ["%PDF-1.4\n"]
    offsets = [0]
    for object_id, object_body in enumerate(objects, start=1):
        offsets.append(sum(len(chunk.encode("utf-8")) for chunk in output))
        output.append(f"{object_id} 0 obj\n{object_body}\nendobj\n")

    xref_offset = sum(len(chunk.encode("utf-8")) for chunk in output)
    output.append(f"xref\n0 {len(objects) + 1}\n")
    output.append("0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.append(f"{offset:010d} 00000 n \n")
    output.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_object_id} 0 R /Info {info_object_id} 0 R >>\n"
    )
    output.append(f"startxref\n{xref_offset}\n%%EOF\n")
    path.write_text("".join(output), encoding="utf-8")


def _parse_svg_sheet(path: Path) -> Tuple[float, float, str]:
    root = ElementTree.fromstring(path.read_text(encoding="utf-8"))
    width_mm = _parse_mm_value(root.attrib.get("width")) or _viewbox_size(root.attrib.get("viewBox"), 2)
    height_mm = _parse_mm_value(root.attrib.get("height")) or _viewbox_size(root.attrib.get("viewBox"), 3)
    if width_mm is None or height_mm is None:
        raise ValueError(f"SVG sheet is missing width/height: {path}")

    commands: List[str] = []
    _render_svg_children(root, height_mm, commands)
    return width_mm, height_mm, "\n".join(commands)


def _render_svg_children(node, page_height_mm: float, commands: List[str]) -> None:
    for child in list(node):
        tag = _local_name(child.tag)
        if tag in {"defs", "marker", "polygon", "polyline"}:
            continue
        if tag in {"svg", "g"}:
            _render_svg_children(child, page_height_mm, commands)
            continue
        if tag == "rect":
            commands.extend(_rect_commands(child.attrib, page_height_mm))
            continue
        if tag == "line":
            commands.extend(_line_commands(child.attrib, page_height_mm))
            continue
        if tag == "path":
            commands.extend(_path_commands(child.attrib, page_height_mm))
            continue
        if tag == "text":
            commands.extend(_text_commands(child, page_height_mm))


def _rect_commands(attrs: dict, page_height_mm: float) -> List[str]:
    x = _parse_float(attrs.get("x"))
    y = _parse_float(attrs.get("y"))
    width = _parse_float(attrs.get("width"))
    height = _parse_float(attrs.get("height"))
    if None in {x, y, width, height}:
        return []

    fill = _parse_color(attrs.get("fill"))
    stroke = _parse_color(attrs.get("stroke"))
    stroke_width = (_parse_float(attrs.get("stroke-width")) or 0.0) * MM_TO_PT
    x_pt = x * MM_TO_PT
    y_pt = (page_height_mm - y - height) * MM_TO_PT
    width_pt = width * MM_TO_PT
    height_pt = height * MM_TO_PT

    commands: List[str] = []
    if fill is not None:
        commands.append(_fill_color_command(fill))
    if stroke is not None:
        commands.append(_stroke_color_command(stroke))
        commands.append(f"{stroke_width:.3f} w")
    operator = _paint_operator(fill is not None, stroke is not None, even_odd=False)
    if operator is None:
        return []
    commands.append(f"{x_pt:.3f} {y_pt:.3f} {width_pt:.3f} {height_pt:.3f} re {operator}")
    return commands


def _line_commands(attrs: dict, page_height_mm: float) -> List[str]:
    x1 = _parse_float(attrs.get("x1"))
    y1 = _parse_float(attrs.get("y1"))
    x2 = _parse_float(attrs.get("x2"))
    y2 = _parse_float(attrs.get("y2"))
    stroke = _parse_color(attrs.get("stroke"))
    if None in {x1, y1, x2, y2} or stroke is None:
        return []
    stroke_width = (_parse_float(attrs.get("stroke-width")) or 0.0) * MM_TO_PT
    sx1, sy1 = _to_pdf_point(x1, y1, page_height_mm)
    sx2, sy2 = _to_pdf_point(x2, y2, page_height_mm)
    return [
        _stroke_color_command(stroke),
        f"{stroke_width:.3f} w",
        "[] 0 d",
        f"{sx1:.3f} {sy1:.3f} m",
        f"{sx2:.3f} {sy2:.3f} l",
        "S",
    ]


def _path_commands(attrs: dict, page_height_mm: float) -> List[str]:
    path_data = attrs.get("d", "")
    if not path_data:
        return []

    fill = _parse_color(attrs.get("fill"))
    stroke = _parse_color(attrs.get("stroke"))
    stroke_width = (_parse_float(attrs.get("stroke-width")) or 0.0) * MM_TO_PT
    even_odd = attrs.get("fill-rule", "") == "evenodd"

    commands = _svg_path_to_pdf(path_data, page_height_mm)
    if not commands:
        return []

    rendered: List[str] = []
    if fill is not None:
        rendered.append(_fill_color_command(fill))
    if stroke is not None:
        rendered.append(_stroke_color_command(stroke))
        rendered.append(f"{stroke_width:.3f} w")
        rendered.append("[] 0 d")
    operator = _paint_operator(fill is not None, stroke is not None, even_odd=even_odd)
    if operator is None:
        return []
    return rendered + commands + [operator]


def _text_commands(node, page_height_mm: float) -> List[str]:
    attrs = node.attrib
    x = _parse_float(attrs.get("x"))
    y = _parse_float(attrs.get("y"))
    font_size = _parse_float(attrs.get("font-size"))
    fill = _parse_color(attrs.get("fill")) or (0.0, 0.0, 0.0)
    text_value = "".join(node.itertext())
    if x is None or y is None or font_size is None or not text_value:
        return []

    x_pt, y_pt = _to_pdf_point(x, y, page_height_mm)
    font_size_pt = font_size * MM_TO_PT
    font_name = "/F2" if _is_bold(attrs.get("font-weight")) else "/F1"
    return [
        _fill_color_command(fill),
        "BT",
        f"{font_name} {font_size_pt:.3f} Tf",
        f"1 0 0 1 {x_pt:.3f} {y_pt:.3f} Tm",
        f"({_escape_text(text_value)}) Tj",
        "ET",
    ]


def _svg_path_to_pdf(path_data: str, page_height_mm: float) -> List[str]:
    tokens = PATH_TOKEN_RE.findall(path_data)
    if not tokens:
        return []

    commands: List[str] = []
    current_point = (0.0, 0.0)
    subpath_start = (0.0, 0.0)
    active_command = ""
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            active_command = token
            index += 1
        if not active_command:
            break

        if active_command in "Zz":
            commands.append("h")
            current_point = subpath_start
            active_command = ""
            continue

        params: List[float] = []
        while index < len(tokens) and not tokens[index].isalpha():
            params.append(float(tokens[index]))
            index += 1

        if active_command in "Mm":
            for point_index in range(0, len(params), 2):
                if point_index + 1 >= len(params):
                    break
                current_point = _relative_point(
                    current_point,
                    params[point_index],
                    params[point_index + 1],
                    active_command.islower(),
                )
                x_pt, y_pt = _to_pdf_point(current_point[0], current_point[1], page_height_mm)
                if point_index == 0:
                    commands.append(f"{x_pt:.3f} {y_pt:.3f} m")
                    subpath_start = current_point
                else:
                    commands.append(f"{x_pt:.3f} {y_pt:.3f} l")
            continue

        if active_command in "Ll":
            for point_index in range(0, len(params), 2):
                if point_index + 1 >= len(params):
                    break
                current_point = _relative_point(
                    current_point,
                    params[point_index],
                    params[point_index + 1],
                    active_command.islower(),
                )
                x_pt, y_pt = _to_pdf_point(current_point[0], current_point[1], page_height_mm)
                commands.append(f"{x_pt:.3f} {y_pt:.3f} l")
            continue

        if active_command in "Hh":
            for value in params:
                current_point = (
                    current_point[0] + value if active_command == "h" else value,
                    current_point[1],
                )
                x_pt, y_pt = _to_pdf_point(current_point[0], current_point[1], page_height_mm)
                commands.append(f"{x_pt:.3f} {y_pt:.3f} l")
            continue

        if active_command in "Vv":
            for value in params:
                current_point = (
                    current_point[0],
                    current_point[1] + value if active_command == "v" else value,
                )
                x_pt, y_pt = _to_pdf_point(current_point[0], current_point[1], page_height_mm)
                commands.append(f"{x_pt:.3f} {y_pt:.3f} l")

    return commands


def _relative_point(
    current_point: Tuple[float, float],
    x: float,
    y: float,
    relative: bool,
) -> Tuple[float, float]:
    if relative:
        return current_point[0] + x, current_point[1] + y
    return x, y


def _paint_operator(fill: bool, stroke: bool, even_odd: bool) -> Optional[str]:
    if fill and stroke:
        return "B*" if even_odd else "B"
    if fill:
        return "f*" if even_odd else "f"
    if stroke:
        return "S"
    return None


def _to_pdf_point(x_mm: float, y_mm: float, page_height_mm: float) -> Tuple[float, float]:
    return x_mm * MM_TO_PT, (page_height_mm - y_mm) * MM_TO_PT


def _fill_color_command(color: Tuple[float, float, float]) -> str:
    return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg"


def _stroke_color_command(color: Tuple[float, float, float]) -> str:
    return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG"


def _parse_color(value: Optional[str]) -> Optional[Tuple[float, float, float]]:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped == "none":
        return None
    if stripped.startswith("#") and len(stripped) == 7:
        return tuple(int(stripped[index : index + 2], 16) / 255.0 for index in (1, 3, 5))
    if stripped.startswith("#") and len(stripped) == 4:
        return tuple(int(stripped[index] * 2, 16) / 255.0 for index in (1, 2, 3))
    return None


def _parse_mm_value(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    stripped = value.strip()
    if stripped.endswith("mm"):
        stripped = stripped[:-2]
    return _parse_float(stripped)


def _viewbox_size(view_box: Optional[str], index: int) -> Optional[float]:
    if not view_box:
        return None
    parts = view_box.strip().split()
    if len(parts) != 4:
        return None
    return _parse_float(parts[index])


def _parse_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _local_name(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _is_bold(value: Optional[str]) -> bool:
    if value is None:
        return False
    stripped = value.strip()
    if stripped.isdigit():
        return int(stripped) >= 600
    return stripped.lower() in {"bold", "bolder"}


def _escape_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
