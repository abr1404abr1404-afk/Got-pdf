"""Permanent PDF redaction for explicitly selected page regions.

Coordinates are normalized to the unrotated page media box (0..1).
The caller must provide a reviewed output PDF and explicit region list.
"""
from __future__ import annotations

import json
import math
from typing import Any

import pymupdf

MAX_REDACTION_PAGES = 200
MAX_REDACTION_REGIONS = 2000


def _parse_regions(raw: str | dict[str, Any], page_count: int) -> dict[int, list[tuple[float, float, float, float]]]:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("بيانات مناطق الحجب غير صالحة.") from exc
    entries = payload.get("regions") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries or len(entries) > MAX_REDACTION_REGIONS:
        raise ValueError("أضف منطقة حجب واحدة على الأقل، ولا تتجاوز 2000 منطقة.")
    grouped: dict[int, list[tuple[float, float, float, float]]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("إحدى مناطق الحجب غير صالحة.")
        try:
            page_number = int(entry.get("page"))
            coords = entry.get("rect")
            if not isinstance(coords, list) or len(coords) != 4:
                raise ValueError
            x0, y0, x1, y1 = (float(value) for value in coords)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("إحداثيات إحدى مناطق الحجب غير صالحة.") from exc
        if page_number < 1 or page_number > page_count:
            raise ValueError("رقم صفحة الحجب خارج نطاق الملف.")
        if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
            raise ValueError("إحداثيات الحجب يجب أن تكون أرقامًا محدودة.")
        if x0 < 0 or y0 < 0 or x1 > 1 or y1 > 1 or x1 <= x0 or y1 <= y0:
            raise ValueError("يجب أن تكون منطقة الحجب مستطيلًا صحيحًا داخل الصفحة.")
        grouped.setdefault(page_number - 1, []).append((x0, y0, x1, y1))
    return grouped


def redact_pdf_bytes(pdf_bytes: bytes, regions_json: str | dict[str, Any]) -> bytes:
    """Permanently remove text, image pixels and vector graphics in selected areas."""
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError("الملف ليس PDF صالحًا.") from exc
    try:
        if document.needs_pass:
            raise ValueError("لا يمكن تطبيق الحجب على ملف محمي بكلمة مرور.")
        if not 1 <= document.page_count <= MAX_REDACTION_PAGES:
            raise ValueError("عدد صفحات الملف خارج الحد المسموح للحجب.")
        grouped = _parse_regions(regions_json, document.page_count)
        for page_index, boxes in grouped.items():
            page = document.load_page(page_index)
            original_rotation = page.rotation
            # PyMuPDF redaction coordinates are applied against the unrotated page.
            if original_rotation:
                page.set_rotation(0)
            # page.rect reflects the visible crop box after resetting rotation.
            media = page.rect
            for x0, y0, x1, y1 in boxes:
                rect = pymupdf.Rect(
                    media.x0 + x0 * media.width,
                    media.y0 + y0 * media.height,
                    media.x0 + x1 * media.width,
                    media.y0 + y1 * media.height,
                )
                if rect.width < 1 or rect.height < 1:
                    raise ValueError("منطقة الحجب صغيرة جدًا؛ وسّع المستطيل ثم أعد المحاولة.")
                page.add_redact_annot(rect, fill=(0, 0, 0), cross_out=False)
            # Remove overlapping annotations, widgets and links as well as page content.
            redaction_rects = [annot.rect for annot in (page.annots() or []) if annot.type[0] == 12]
            for annot in list(page.annots() or []):
                if annot.type[0] != 12 and any(annot.rect.intersects(r) for r in redaction_rects):
                    page.delete_annot(annot)
            for widget in list(page.widgets() or []):
                if any(widget.rect.intersects(r) for r in redaction_rects):
                    page.delete_widget(widget)
            for link in page.get_links():
                link_rect = link.get("from")
                if link_rect and any(pymupdf.Rect(link_rect).intersects(r) for r in redaction_rects):
                    page.delete_link(link)
            page.apply_redactions(images=2, graphics=1, text=0)
            if original_rotation:
                page.set_rotation(original_rotation)
        # Strip document-level metadata and embedded attachments from the redacted copy.
        document.set_metadata({})
        document.set_xml_metadata("")
        for attachment_name in document.embfile_names():
            document.embfile_del(attachment_name)
        output = document.tobytes(garbage=4, deflate=True, clean=True)
        if not output.startswith(b"%PDF-"):
            raise ValueError("تعذّر إنشاء ملف PDF محجوب صالح.")
        return output
    finally:
        document.close()
