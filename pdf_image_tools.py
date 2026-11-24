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
            seen_xrefs: set[int] = set()
            for info in infos:
                xref = int(info.get("xref") or 0)
                if xref <= 0 or xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
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
        seen_targets: set[tuple[int, int]] = set()
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
            target_key = (page_number, xref)
            if target_key in seen_targets:
                raise ValueError("عدّل موضع صورة واحد من كل مجموعة صور متطابقة في الطلب الواحد.")
            seen_targets.add(target_key)
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


MAX_OBJECT_ITEMS = 500
MAX_TEXT_PREVIEW_CHARS = 240


def _normalized_rect(rect: pymupdf.Rect, page_rect: pymupdf.Rect) -> list[float]:
    return [
        round(max(0.0, min(1.0, (rect.x0 - page_rect.x0) / page_rect.width)), 5),
        round(max(0.0, min(1.0, (rect.y0 - page_rect.y0) / page_rect.height)), 5),
        round(max(0.0, min(1.0, (rect.x1 - page_rect.x0) / page_rect.width)), 5),
        round(max(0.0, min(1.0, (rect.y1 - page_rect.y0) / page_rect.height)), 5),
    ]


def _overlap_ratio(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    intersection = a & b
    if intersection.is_empty or intersection.get_area() <= 0:
        return 0.0
    return intersection.get_area() / max(min(a.get_area(), b.get_area()), 1.0)


def inspect_pdf_objects(data: bytes) -> dict[str, Any]:
    """Return a bounded inventory of text spans, raster images, vector drawings and annotations."""
    doc = _open(data)
    objects: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    try:
        for page_index in range(doc.page_count):
            if len(objects) >= MAX_OBJECT_ITEMS:
                warnings.append({"type": "inventory_truncated",
                                 "message": "تم إيقاف الفهرسة عند 500 عنصر لحماية الأداء."})
                break
            page = doc.load_page(page_index)
            page_rect = page.rect
            text_spans: list[tuple[pymupdf.Rect, str]] = []
            page_images: list[tuple[pymupdf.Rect, dict[str, Any]]] = []

            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        raw_text = str(span.get("text", "")).strip()
                        if not raw_text:
                            continue
                        rect = pymupdf.Rect(span.get("bbox", (0, 0, 0, 0)))
                        text_spans.append((rect, raw_text))
                        objects.append({
                            "id": f"p{page_index + 1}-text-{len(text_spans)}",
                            "type": "text",
                            "page": page_index + 1,
                            "text": raw_text[:MAX_TEXT_PREVIEW_CHARS],
                            "truncated": len(raw_text) > MAX_TEXT_PREVIEW_CHARS,
                            "rect": _normalized_rect(rect, page_rect),
                        })
                        if len(objects) >= MAX_OBJECT_ITEMS:
                            break
                    if len(objects) >= MAX_OBJECT_ITEMS:
                        break
                if len(objects) >= MAX_OBJECT_ITEMS:
                    break

            if len(objects) < MAX_OBJECT_ITEMS:
                for image_index, info in enumerate(page.get_image_info(xrefs=True), start=1):
                    rect = pymupdf.Rect(info.get("bbox", (0, 0, 0, 0)))
                    item = {
                        "id": f"p{page_index + 1}-image-{image_index}",
                        "type": "image",
                        "page": page_index + 1,
                        "width": int(info.get("width") or 0),
                        "height": int(info.get("height") or 0),
                        "xref": int(info.get("xref") or 0),
                        "rect": _normalized_rect(rect, page_rect),
                    }
                    page_images.append((rect, item))
                    objects.append(item)
                    if len(objects) >= MAX_OBJECT_ITEMS:
                        break

            if len(objects) < MAX_OBJECT_ITEMS:
                for drawing_index, drawing in enumerate(page.get_drawings(), start=1):
                    rect_value = drawing.get("rect")
                    if not rect_value:
                        continue
                    rect = pymupdf.Rect(rect_value)
                    objects.append({
                        "id": f"p{page_index + 1}-vector-{drawing_index}",
                        "type": "vector",
                        "page": page_index + 1,
                        "items": min(len(drawing.get("items", [])), 10000),
                        "fill": list(drawing["fill"]) if drawing.get("fill") else None,
                        "stroke": list(drawing["color"]) if drawing.get("color") else None,
                        "rect": _normalized_rect(rect, page_rect),
                    })
                    if len(objects) >= MAX_OBJECT_ITEMS:
                        break

            if len(objects) < MAX_OBJECT_ITEMS:
                for annotation_index, annotation in enumerate(page.annots() or [], start=1):
                    rect = pymupdf.Rect(annotation.rect)
                    objects.append({
                        "id": f"p{page_index + 1}-annotation-{annotation_index}",
                        "type": "annotation",
                        "page": page_index + 1,
                        "subtype": annotation.type[1] if annotation.type else "unknown",
                        "rect": _normalized_rect(rect, page_rect),
                    })
                    if len(objects) >= MAX_OBJECT_ITEMS:
                        break

            for image_index, (image_rect, image_obj) in enumerate(page_images):
                for text_rect, _text in text_spans:
                    if _overlap_ratio(image_rect, text_rect) >= 0.10:
                        warnings.append({
                            "type": "image_text_overlap",
                            "page": page_index + 1,
                            "object_id": image_obj["id"],
                            "message": "تتداخل الصورة مع نص؛ راجع المنطقة قبل التعديل.",
                        })
                        break
                for other_rect, other in page_images[image_index + 1:]:
                    if _overlap_ratio(image_rect, other_rect) >= 0.10:
                        warnings.append({
                            "type": "image_image_overlap",
                            "page": page_index + 1,
                            "object_id": image_obj["id"],
                            "other_object_id": other["id"],
                            "message": "تتداخل هذه الصورة مع صورة أخرى؛ قد يتأثر مظهرهما عند التعديل.",
                        })

        counts = {kind: sum(1 for item in objects if item["type"] == kind)
                  for kind in ("text", "image", "vector", "annotation")}
        if len(objects) >= MAX_OBJECT_ITEMS and not any(w["type"] == "inventory_truncated" for w in warnings):
            warnings.append({"type": "inventory_truncated",
                             "message": "تم إيقاف الفهرسة عند 500 عنصر لحماية الأداء."})
        return {"pages": doc.page_count, "count": len(objects), "counts": counts,
                "objects": objects, "warnings": warnings}
    finally:
        doc.close()


MAX_VECTOR_EDIT_OPS = 20


def edit_pdf_vector_objects(data: bytes, operations: list[dict[str, Any]]) -> bytes:
    """Delete isolated vector drawings only; reject intersecting content and preserve input bytes."""
    if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_VECTOR_EDIT_OPS:
        raise ValueError("حدد رسمًا واحدًا على الأقل، وبحد أقصى 20 عملية في المرة.")
    doc = _open(data)
    try:
        seen: set[tuple[int, int]] = set()
        page_targets: dict[int, list[pymupdf.Rect]] = {}
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("action") != "delete":
                raise ValueError("العملية المدعومة حاليًا هي حذف رسم متجهي معزول فقط.")
            try:
                page_number = int(operation["page"])
                object_id = str(operation["object_id"])
                coords = operation["rect"]
                if not isinstance(coords, list) or len(coords) != 4:
                    raise ValueError
                normalized = [float(value) for value in coords]
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError("بيانات الرسم أو إحداثياته غير صالحة.") from exc
            prefix = f"p{page_number}-vector-"
            if not object_id.startswith(prefix):
                raise ValueError("معرّف الرسم لا يطابق الصفحة المحددة.")
            try:
                drawing_index = int(object_id[len(prefix):]) - 1
            except ValueError as exc:
                raise ValueError("معرّف الرسم غير صالح.") from exc
            if not 1 <= page_number <= doc.page_count or drawing_index < 0:
                raise ValueError("مرجع الرسم خارج نطاق الملف.")
            if not all(math.isfinite(value) for value in normalized):
                raise ValueError("إحداثيات الرسم غير صالحة.")
            x0, y0, x1, y1 = normalized
            if x0 < 0 or y0 < 0 or x1 > 1 or y1 > 1 or x1 <= x0 or y1 <= y0:
                raise ValueError("مستطيل الرسم يجب أن يقع داخل الصفحة.")
            target_key = (page_number, drawing_index)
            if target_key in seen:
                raise ValueError("لا تكرر الرسم نفسه في الطلب.")
            seen.add(target_key)
            page = doc.load_page(page_number - 1)
            page_rect = page.rect
            drawings = page.get_drawings()
            if drawing_index >= len(drawings):
                raise ValueError("لم يتم العثور على الرسم المحدد؛ أعد فهرسة الملف.")
            drawing = drawings[drawing_index]
            target_rect = pymupdf.Rect(drawing.get("rect") or (0, 0, 0, 0))
            supplied_rect = pymupdf.Rect(
                page_rect.x0 + x0 * page_rect.width,
                page_rect.y0 + y0 * page_rect.height,
                page_rect.x0 + x1 * page_rect.width,
                page_rect.y0 + y1 * page_rect.height,
            )
            if (not target_rect.intersects(supplied_rect)
                    or abs(target_rect.x0 - supplied_rect.x0) > 1.5
                    or abs(target_rect.y0 - supplied_rect.y0) > 1.5
                    or abs(target_rect.x1 - supplied_rect.x1) > 1.5
                    or abs(target_rect.y1 - supplied_rect.y1) > 1.5):
                raise ValueError("تغيّر موضع الرسم؛ أعد فهرسة الملف ثم حاول مجددًا.")

            # A vector drawing may be visually layered over other content. Reject any
            # bounding-box intersection rather than risk removing unrelated content.
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text_rect = pymupdf.Rect(span.get("bbox", (0, 0, 0, 0)))
                        if target_rect.intersects(text_rect):
                            raise ValueError("الرسم يتداخل مع نص؛ لم يتم إجراء أي تعديل. اختر رسمًا منفصلًا.")
            for info in page.get_image_info(xrefs=True):
                image_rect = pymupdf.Rect(info.get("bbox", (0, 0, 0, 0)))
                if target_rect.intersects(image_rect):
                    raise ValueError("الرسم يتداخل مع صورة؛ لم يتم إجراء أي تعديل. اختر رسمًا منفصلًا.")
            for other_index, other in enumerate(drawings):
                if other_index == drawing_index:
                    continue
                other_rect = pymupdf.Rect(other.get("rect") or (0, 0, 0, 0))
                if target_rect.intersects(other_rect):
                    raise ValueError("الرسم يتداخل مع رسم متجهي آخر؛ لم يتم إجراء أي تعديل.")

            page_targets.setdefault(page_number, []).append(target_rect)

        # Apply only after every requested target passed validation, so failures
        # never produce a partially edited output.
        for page_number, rects in page_targets.items():
            page = doc.load_page(page_number - 1)
            for rect in rects:
                page.add_redact_annot(rect, fill=None, cross_out=False)
            page.apply_redactions(images=0, graphics=1, text=0)

        output = doc.tobytes(garbage=4, deflate=True, clean=True)
        if not output.startswith(b"%PDF-"):
            raise ValueError("تعذّر إنشاء نسخة PDF المعدّلة.")
        return output
    finally:
        doc.close()
