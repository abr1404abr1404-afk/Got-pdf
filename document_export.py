"""Generate editable Office files from user-reviewed extracted document text."""
from __future__ import annotations

import io
from typing import Any

MAX_EXPORT_PAGES = 100
MAX_EXPORT_CHARS = 200_000


def _clean_pages(pages: Any) -> list[dict[str, Any]]:
    if not isinstance(pages, list) or not pages or len(pages) > MAX_EXPORT_PAGES:
        raise ValueError("عدد صفحات التصدير غير صالح أو يتجاوز 100 صفحة.")
    cleaned: list[dict[str, Any]] = []
    total = 0
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise ValueError("بيانات إحدى الصفحات غير صالحة.")
        number = page.get("page", index + 1)
        text = page.get("text")
        if not isinstance(number, int) or number < 1 or number > 100000:
            raise ValueError("رقم صفحة التصدير غير صالح.")
        if not isinstance(text, str):
            raise ValueError("نص إحدى الصفحات غير صالح.")
        total += len(text)
        if total > MAX_EXPORT_CHARS:
            raise ValueError("النص يتجاوز حد التصدير البالغ 200 ألف حرف.")
        cleaned.append({"page": number, "text": text[:MAX_EXPORT_CHARS]})
    if not any(page["text"].strip() for page in cleaned):
        raise ValueError("لا يوجد نص قابل للتصدير. شغّل OCR أو استخرج النص أولًا.")
    return cleaned


def create_docx(pages: Any) -> bytes:
    """Create an editable DOCX with page headings and RTL paragraph direction."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    cleaned = _clean_pages(pages)
    document = Document()
    document.core_properties.title = "النص المستخرج من الفلقي PDF"
    document.core_properties.author = "الفلقي PDF"
    for page in cleaned:
        heading = document.add_heading(f"الصفحة {page['page']}", level=2)
        heading.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for paragraph_text in page["text"].splitlines() or [page["text"]]:
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p_pr = paragraph._p.get_or_add_pPr()
            bidi = OxmlElement("w:bidi")
            bidi.set(qn("w:val"), "1")
            p_pr.append(bidi)
            run = paragraph.add_run(paragraph_text)
            run.font.name = "Arial"
            r_pr = run._element.get_or_add_rPr()
            r_fonts = r_pr.rFonts
            if r_fonts is not None:
                r_fonts.set(qn("w:cs"), "Arial")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def create_xlsx(pages: Any) -> bytes:
    """Create a workbook with one row per extracted text line."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    cleaned = _clean_pages(pages)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "النص المستخرج"
    sheet.append(["رقم الصفحة", "رقم السطر", "النص"])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="245A73")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for page in cleaned:
        for line_number, line in enumerate(page["text"].splitlines() or [page["text"]], 1):
            if line.strip():
                sheet.append([page["page"], line_number, line])
                sheet.cell(sheet.max_row, 3).alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in enumerate((14, 12, 90), 1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.sheet_view.rightToLeft = True
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
