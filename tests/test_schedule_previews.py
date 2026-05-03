from __future__ import annotations

from pathlib import Path

from ifc_book_prototype.domain import ScheduleRow, ScheduleSheet
from ifc_book_prototype.profiles import load_style_profile
from ifc_book_prototype.render_pdf import write_pdf_from_svg_sheets
from ifc_book_prototype.render_svg import render_schedule_svg


def test_schedule_svg_includes_pdf_safe_preview_column(tmp_path: Path) -> None:
    profile = load_style_profile()
    schedule = ScheduleSheet(
        schedule_id="opening_schedule_01",
        sheet_id="A-601",
        title="Opening Type Schedule",
        category="opening_schedule",
        label_header="Type / Label",
        rows=[
            ScheduleRow(ifc_class="IfcDoor", label="Single leaf", storey_name="Ground Floor", count=3),
            ScheduleRow(ifc_class="IfcWindow", label="Fixed window", storey_name="Ground Floor", count=5),
            ScheduleRow(ifc_class="IfcStair", label="Main stair", storey_name="Ground Floor", count=1),
            ScheduleRow(ifc_class="IfcSpace", label="Office", storey_name="Level 01", count=8),
        ],
        notes=["Preview symbols are schematic, not element-scale detail."],
    )

    svg = render_schedule_svg(schedule, profile)

    assert "Preview" in svg
    assert "Single leaf" in svg
    assert "Fixed window" in svg
    assert svg.count("<path") >= 2
    assert svg.count("<rect") >= 4

    svg_path = tmp_path / "schedule.svg"
    pdf_path = tmp_path / "schedule.pdf"
    svg_path.write_text(svg, encoding="utf-8")

    write_pdf_from_svg_sheets(pdf_path, [svg_path])

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
