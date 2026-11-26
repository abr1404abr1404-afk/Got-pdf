"""Client for a self-hosted PaddleOCR-VL document parsing service.

The heavy model runs in a separately managed open-source worker; the lightweight
PDF API only forwards the uploaded document to the configured private service.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any

import httpx


class PaddleVLError(ValueError):
    """A bounded, user-safe PaddleOCR-VL service error."""


def markdown_pages_to_docx(pages: list[dict]) -> bytes:
    """Build an editable DOCX from the official Markdown response."""
    import io, re
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    def rtl(value):
        return any("\u0600" <= ch <= "\u06ff" for ch in value)

    def set_direction(paragraph, is_rtl):
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT if is_rtl else WD_ALIGN_PARAGRAPH.LEFT
        if is_rtl:
            ppr = paragraph._p.get_or_add_pPr()
            bidi = OxmlElement("w:bidi")
            bidi.set(qn("w:val"), "1")
            ppr.append(bidi)
        for run in paragraph.runs:
            if rtl(run.text):
                rpr = run._r.get_or_add_rPr()
                tag = OxmlElement("w:rtl")
                tag.set(qn("w:val"), "1")
                rpr.append(tag)

    if not pages or len(pages) > 100:
        raise PaddleVLError("عدد صفحات المستند غير صالح لإنشاء Word.")
    doc = Document()
    doc.core_properties.title = "مستند محلل - الفلقي PDF"
    for page_no, page in enumerate(pages):
        if page_no:
            doc.add_page_break()
        lines = str(page.get("markdown") or "").splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            if line.startswith("|") and i + 1 < len(lines) and re.search(r"-{3,}", lines[i + 1]):
                raw_rows = [line]
                i += 2
                while i < len(lines) and lines[i].strip().startswith("|"):
                    raw_rows.append(lines[i].strip())
                    i += 1
                rows = [[x.strip() for x in row.strip("|").split("|")] for row in raw_rows]
                width = max(map(len, rows))
                table = doc.add_table(rows=len(rows), cols=width)
                table.style = "Table Grid"
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                for ri, row in enumerate(rows):
                    for ci in range(width):
                        value = row[ci] if ci < len(row) else ""
                        cell = table.cell(ri, ci)
                        cell.text = value
                        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                        for p in cell.paragraphs:
                            set_direction(p, rtl(value))
                            if ri == 0:
                                for run in p.runs:
                                    run.bold = True
                continue
            heading = re.match(r"^(#{1,6})\s+(.+)$", line)
            bullet = re.match(r"^[-*+]\s+(.+)$", line)
            numbered = re.match(r"^\d+[.)]\s+(.+)$", line)
            if heading:
                p = doc.add_paragraph(style=f"Heading {min(3, len(heading.group(1)))}")
                value = heading.group(2)
            elif bullet or numbered:
                value = (bullet or numbered).group(1)
                p = doc.add_paragraph(style="List Bullet" if bullet else "List Number")
            else:
                parts = [line]
                i += 1
                while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("|") and not re.match(r"^(#{1,6})\s+|^[-*+]\s+|^\d+[.)]\s+", lines[i].strip()):
                    parts.append(lines[i].strip())
                    i += 1
                value = " ".join(parts)
                p = doc.add_paragraph()
                p.add_run(value)
                set_direction(p, rtl(value))
                continue
            p.add_run(value)
            set_direction(p, rtl(value))
            i += 1
    output = io.BytesIO()
    doc.save(output)
    data = output.getvalue()
    if not data.startswith(b"PK") or len(data) > 30 * 1024 * 1024:
        raise PaddleVLError("تعذّر إنشاء ملف Word صالح ضمن الحجم المسموح.")
    return data


def normalize_paddle_vl_response(payload: dict[str, Any]) -> dict:
    if not isinstance(payload, dict):
        raise PaddleVLError("استجابة محرك تحليل المستندات غير صالحة.")
    if payload.get("errorCode", 0) not in (0, None):
        raise PaddleVLError(str(payload.get("errorMsg") or "تعذّر تحليل المستند.")[:300])
    result = payload.get("result")
    raw_pages = result.get("layoutParsingResults") if isinstance(result, dict) else None
    if not isinstance(raw_pages, list) or not raw_pages:
        raise PaddleVLError("لم يتمكن محرك التحليل من استخراج صفحات المستند.")
    pages, markdown_parts = [], []
    for index, page in enumerate(raw_pages):
        if not isinstance(page, dict):
            continue
        markdown = page.get("markdown") or {}
        md_text = markdown.get("text", "") if isinstance(markdown, dict) else ""
        if md_text:
            markdown_parts.append(str(md_text))
        pages.append({"page": index + 1,
                      "layout": page.get("prunedResult") if isinstance(page.get("prunedResult"), dict) else {},
                      "markdown": str(md_text)})
    if not pages:
        raise PaddleVLError("لم يتمكن محرك التحليل من استخراج صفحات المستند.")
    return {"engine": "PaddleOCR-VL-1.6", "page_count": len(pages), "pages": pages,
            "markdown": "\n\n".join(markdown_parts),
            "log_id": str(payload.get("logId") or "")[:128]}


async def parse_with_paddle_vl(
    data: bytes,
    base_url: str,
    file_type: int,
    api_key: str = "",
    export_docx: bool = False,
    timeout_seconds: int = 300,
) -> tuple[dict, bytes | None]:
    if not data:
        raise PaddleVLError("الملف فارغ.")
    if file_type not in (0, 1):
        raise PaddleVLError("نوع الملف غير مدعوم.")
    payload = {
        "file": base64.b64encode(data).decode("ascii"),
        "fileType": file_type,
        "visualize": False,
        "useLayoutDetection": True,
        "restructurePages": True,
        "mergeTables": True,
        "prettifyMarkdown": True,
    }
    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    timeout = httpx.Timeout(timeout_seconds, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(base_url.rstrip("/") + "/layout-parsing", json=payload, headers=headers)
        response.raise_for_status()
        try:
            response_payload = response.json()
        except ValueError as exc:
            raise PaddleVLError("أعاد محرك التحليل استجابة غير مفهومة.") from exc
    parsed = normalize_paddle_vl_response(response_payload)
    docx_bytes = markdown_pages_to_docx(parsed["pages"]) if export_docx else None
    return parsed, docx_bytes
