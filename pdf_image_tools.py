"""Inspect and edit embedded raster image occurrences in PDF pages."""
from __future__ import annotations

import math
from typing import Any

import pymupdf

MAX_IMAGE_ITEMS = 200
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_EDIT_OPS = 200


def _open(data: bytes):
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("الملف ليس PDF صالحًا.") from exc
    if doc.needs_pass:
        doc.close()
        raise ValueError("افتح الملف المحمي بكلمة المرور أولًا.")
    if not 1 <= doc.page_count <= 200:
        doc.close()
        raise ValueError("عدد صفحات الملف خارج الحد المسموح.")
    return doc


def list_pdf_images(data: bytes) -> list[dict[str, Any]]:
    doc = _open(data)
    items: list[dict[str, Any]] = []
    total_bytes = 0
    try:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            infos = page.get_image_info(xrefs=True)
            for info in infos:
                xref = int(info.get("xref") or 0)
                if xref <= 0:
                    continue
                bbox = pymupdf.Rect(info["bbox"])
                rects = page.get_image_rects(xref)
                if not rects:
                    rects = [bbox]
                extracted = doc.extract_image(xref)
                image_data = extracted.get("image", b"")
                if not image_data:
                    continue
                total_bytes += len(image_data)
                if total_bytes > MAX_IMAGE_BYTES:
                    raise ValueError("إجمالي معاينات الصور يتجاوز الحد. جرّب ملفًا أصغر.")
                for occurrence, rect in enumerate(rects):
                    items.append({
                        "id": f"{page_index + 1}:{xref}:{occurrence}",
                        "page": page_index + 1,
                        "xref": xref,
                        "occurrence": occurrence,
                        "width": int(extracted.get("width") or info.get("width") or 0),
                        "height": int(extracted.get("height") or info.get("height") or 0),
                        "extension": extracted.get("ext", "bin"),
                        "mime": "image/png" if extracted.get("ext") == "png" else "image/jpeg",
                        "data": __import__("base64").b64encode(image_data).decode("ascii"),
                        "rect": [
                            max(0.0, min(1.0, (rect.x0 - page.rect.x0) / page.rect.width)),
                            max(0.0, min(1.0, (rect.y0 - page.rect.y0) / page.rect.height)),
                            max(0.0, min(1.0, (rect.x1 - page.rect.x0) / page.rect.width)),
                            max(0.0, min(1.0, (rect.y1 - page.rect.y0) / page.rect.height)),
                        ],
                    })
                    if len(items) > MAX_IMAGE_ITEMS:
                        raise ValueError("عدد الصور يتجاوز الحد (200 صورة).")
        return items
    finally:
        doc.close()


def edit_pdf_images(data: bytes, operations: list[dict[str, Any]]) -> bytes:
    if not isinstance(operations, list) or not operations or len(operations) > MAX_IMAGE_EDIT_OPS:
        raise ValueError("حدد صورة واحدة على الأقل، وبحد أقصى 200 عملية.")
    doc = _open(data)
    try:
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError("إحدى عمليات الصور غير صالحة.")
            try:
                page_number = int(operation["page"])
                xref = int(operation["xref"])
                occurrence = int(operation.get("occurrence", 0))
                action = operation["action"]
                coords = operation["rect"]
                if not isinstance(coords, list) or len(coords) != 4:
                    raise ValueError
                x0, y0, x1, y1 = (float(v) for v in coords)
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError("بيانات الصورة أو إحداثياتها غير صالحة.") from exc
            if not 1 <= page_number <= doc.page_count or xref <= 0 or occurrence < 0:
                raise ValueError("مرجع الصورة خارج نطاق الملف.")
            if action not in {"delete", "resize"}:
                raise ValueError("العملية المدعومة هي الحذف أو تغيير الحجم.")
            if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
                raise ValueError("إحداثيات الصورة غير صالحة.")
            if x0 < 0 or y0 < 0 or x1 > 1 or y1 > 1 or x1 <= x0 or y1 <= y0:
                raise ValueError("مستطيل الصورة يجب أن يقع داخل الصفحة.")
            page = doc.load_page(page_number - 1)
            image_rects = page.get_image_rects(xref)
            if occurrence >= len(image_rects):
                raise ValueError("لم يتم العثور على موضع الصورة المحدد.")
            original = image_rects[occurrence]
            page_rect = page.rect
            target_rect = pymupdf.Rect(
                page_rect.x0 + x0 * page_rect.width,
                page_rect.y0 + y0 * page_rect.height,
                page_rect.x0 + x1 * page_rect.width,
                page_rect.y0 + y1 * page_rect.height,
            )
            # Reject stale or forged coordinates that do not identify this occurrence.
            if not original.intersects(target_rect) or abs(original.width - target_rect.width) / max(original.width, 1) > 0.12 or abs(original.height - target_rect.height) / max(original.height, 1) > 0.12:
                raise ValueError("موضع الصورة تغيّر؛ أعد تحليل الصور ثم حاول مجددًا.")
            image_bytes = b""
            if action == "resize":
                image_bytes = doc.extract_image(xref).get("image", b"")
                scale = float(operation.get("scale", 1))
                if not math.isfinite(scale) or not 0.1 <= scale <= 4:
                    raise ValueError("حجم الصورة يجب أن يكون بين 10% و400%.")
                width, height = original.width * scale, original.height * scale
                center = original.tl + (original.br - original.tl) * 0.5
                replacement_rect = pymupdf.Rect(
                    center.x - width / 2, center.y - height / 2,
                    center.x + width / 2, center.y + height / 2,
                )
                if not page_rect.contains(replacement_rect):
                    raise ValueError("الحجم الجديد يتجاوز حدود الصفحة. اختر نسبة أصغر.")
            else:
                replacement_rect = None
            page.add_redact_annot(original, fill=None, cross_out=False)
            page.apply_redactions(images=2, graphics=0, text=0)
            if replacement_rect is not None:
                page.insert_image(replacement_rect, stream=image_bytes, keep_proportion=True)
        output = doc.tobytes(garbage=4, deflate=True, clean=True)
        if not output.startswith(b"%PDF-"):
            raise ValueError("تعذّر إنشاء PDF المعدّل.")
        return output
    finally:
        doc.close()
