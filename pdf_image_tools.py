"""Inspect and edit embedded raster image occurrences in PDF pages."""
from __future__ import annotations

import math
import hashlib
import re
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
            if action not in {"delete", "resize", "move", "rotate", "enhance"}:
                raise ValueError("العمليات المدعومة هي الحذف أو تغيير الحجم أو النقل أو التدوير أو تحسين الصورة.")
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
            replacement_rect = None
            if action in {"resize", "move", "rotate", "enhance"}:
                image_bytes = doc.extract_image(xref).get("image", b"")
                if not image_bytes:
                    raise ValueError("تعذّر استخراج بيانات الصورة الأصلية.")
                if action == "resize":
                    scale = float(operation.get("scale", 1))
                    if not math.isfinite(scale) or not 0.1 <= scale <= 4:
                        raise ValueError("حجم الصورة يجب أن يكون بين 10% و400%.")
                    width, height = original.width * scale, original.height * scale
                    center = original.tl + (original.br - original.tl) * 0.5
                    replacement_rect = pymupdf.Rect(
                        center.x - width / 2, center.y - height / 2,
                        center.x + width / 2, center.y + height / 2,
                    )
                elif action == "move":
                    dx, dy = float(operation.get("dx", 0)), float(operation.get("dy", 0))
                    if not math.isfinite(dx) or not math.isfinite(dy) or abs(dx) > 500 or abs(dy) > 500:
                        raise ValueError("إزاحة الصورة يجب أن تكون بين -500 و500 نقطة.")
                    replacement_rect = original + (dx, dy, dx, dy)
                elif action == "rotate":
                    rotation = operation.get("rotation")
                    if isinstance(rotation, bool) or rotation not in {90, 180, 270}:
                        raise ValueError("زاوية تدوير الصورة يجب أن تكون 90 أو 180 أو 270 درجة.")
                    center = original.tl + (original.br - original.tl) * 0.5
                    if rotation in {90, 270}:
                        replacement_rect = pymupdf.Rect(
                            center.x - original.height / 2, center.y - original.width / 2,
                            center.x + original.height / 2, center.y + original.width / 2,
                        )
                    else:
                        replacement_rect = pymupdf.Rect(original)
                else:
                    import io
                    from PIL import Image, ImageEnhance, ImageOps
                    image_info = next((entry for entry in page.get_image_info(xrefs=True)
                                       if int(entry.get("xref") or 0) == xref
                                       and pymupdf.Rect(entry.get("bbox", (0, 0, 0, 0))).intersects(original)), {})
                    if image_info.get("has-mask"):
                        raise ValueError("هذه الصورة تستخدم قناع شفافية؛ لا يمكن تحسينها بأمان في هذه المرحلة.")
                    with Image.open(io.BytesIO(image_bytes)) as source_image:
                        if source_image.width * source_image.height > 20_000_000:
                            raise ValueError("دقة الصورة تتجاوز الحد الآمن للتحسين.")
                        source_image.load()
                        has_alpha = "A" in source_image.getbands() or "transparency" in source_image.info
                        alpha = source_image.convert("RGBA").getchannel("A") if has_alpha else None
                        working = source_image.convert("RGB")
                        filter_name = str(operation.get("filter", ""))
                        if filter_name == "grayscale":
                            working = ImageOps.grayscale(working).convert("RGB")
                        elif filter_name in {"brightness", "contrast", "color", "sharpness"}:
                            factor = float(operation.get("factor", 1))
                            if not math.isfinite(factor) or not 0.5 <= factor <= 2:
                                raise ValueError("قيمة التحسين يجب أن تكون بين 0.5 و2.")
                            enhancer = {"brightness": ImageEnhance.Brightness,
                                        "contrast": ImageEnhance.Contrast,
                                        "color": ImageEnhance.Color,
                                        "sharpness": ImageEnhance.Sharpness}[filter_name]
                            working = enhancer(working).enhance(factor)
                        else:
                            raise ValueError("نوع تحسين الصورة غير معروف.")
                        if alpha is not None:
                            working.putalpha(alpha)
                        output_buffer = io.BytesIO()
                        working.save(output_buffer, format="PNG", optimize=True)
                        image_bytes = output_buffer.getvalue()
                    replacement_rect = pymupdf.Rect(original)
                if not page_rect.contains(replacement_rect):
                    raise ValueError("الموضع أو الحجم الجديد يتجاوز حدود الصفحة.")
            # Redaction changes page content, so refuse all existing overlaps rather
            # than risk erasing text, another image, a vector path, or an annotation.
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        span_rect = pymupdf.Rect(span.get("bbox", (0, 0, 0, 0)))
                        if original.intersects(span_rect):
                            raise ValueError("الصورة تتداخل مع نص؛ لم يتم تعديل الملف.")
                        if replacement_rect is not None and replacement_rect.intersects(span_rect):
                            raise ValueError("الموضع الجديد للصورة سيتداخل مع نص.")
            for other_info in page.get_image_info(xrefs=True):
                other_xref = int(other_info.get("xref") or 0)
                other_rect = pymupdf.Rect(other_info.get("bbox", (0, 0, 0, 0)))
                if other_xref == xref and abs(other_rect.x0-original.x0)<0.01 and abs(other_rect.y0-original.y0)<0.01 and abs(other_rect.x1-original.x1)<0.01 and abs(other_rect.y1-original.y1)<0.01:
                    continue
                if original.intersects(other_rect):
                    raise ValueError("الصورة تتداخل مع صورة أخرى؛ لم يتم التعديل.")
                if replacement_rect is not None and replacement_rect.intersects(other_rect):
                    raise ValueError("الموضع الجديد للصورة سيتداخل مع صورة أخرى.")
            for drawing in page.get_drawings():
                drawing_rect = pymupdf.Rect(drawing.get("rect") or (0, 0, 0, 0))
                if original.intersects(drawing_rect):
                    raise ValueError("الصورة تتداخل مع رسم متجهي؛ لم يتم التعديل.")
                if replacement_rect is not None and replacement_rect.intersects(drawing_rect):
                    raise ValueError("الموضع الجديد للصورة سيتداخل مع رسم متجهي.")
            for annotation in page.annots() or []:
                annotation_rect = pymupdf.Rect(annotation.rect)
                if original.intersects(annotation_rect):
                    raise ValueError("الصورة تتداخل مع تعليق؛ لم يتم التعديل.")
                if replacement_rect is not None and replacement_rect.intersects(annotation_rect):
                    raise ValueError("الموضع الجديد للصورة سيتداخل مع تعليق.")
            page.add_redact_annot(original, fill=None, cross_out=False)
            page.apply_redactions(images=2, graphics=0, text=0)
            if replacement_rect is not None:
                insert_options = {"stream": image_bytes, "keep_proportion": True}
                if action == "rotate":
                    insert_options["rotate"] = int(operation["rotation"])
                page.insert_image(replacement_rect, **insert_options)
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
            page_vectors: list[tuple[pymupdf.Rect, dict[str, Any]]] = []

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
                        color_value = span.get("color")
                        color_hex = f"#{int(color_value):06X}" if isinstance(color_value, int) else None
                        direction = line.get("dir")
                        objects.append({
                            "id": f"p{page_index + 1}-text-{len(text_spans)}",
                            "type": "text",
                            "page": page_index + 1,
                            "text": raw_text[:MAX_TEXT_PREVIEW_CHARS],
                            "text_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                            "truncated": len(raw_text) > MAX_TEXT_PREVIEW_CHARS,
                            "font": str(span.get("font", ""))[:120],
                            "font_size": round(float(span.get("size") or 0), 2),
                            "font_flags": int(span.get("flags") or 0),
                            "color": color_hex,
                            "writing_direction": [round(float(v), 4) for v in direction] if isinstance(direction, (list, tuple)) and len(direction) == 2 else None,
                            "origin": [round(float(v), 2) for v in span.get("origin", [])[:2]] if isinstance(span.get("origin"), (list, tuple)) else None,
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
                    vector_item = {
                        "id": f"p{page_index + 1}-vector-{drawing_index}",
                        "type": "vector",
                        "page": page_index + 1,
                        "items": min(len(drawing.get("items", [])), 10000),
                        "path_types": [str(item[0]) for item in drawing.get("items", [])[:20]],
                        "line_width": round(float(drawing.get("width") or 0), 3),
                        "fill_opacity": drawing.get("fill_opacity"),
                        "stroke_opacity": drawing.get("stroke_opacity"),
                        "fill": list(drawing["fill"]) if drawing.get("fill") else None,
                        "stroke": list(drawing["color"]) if drawing.get("color") else None,
                        "rect": _normalized_rect(rect, page_rect),
                    }
                    page_vectors.append((rect, vector_item))
                    objects.append(vector_item)
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

            # Surface vector overlaps as well: an apparently isolated drawing may
            # be part of a composite icon or sit over raster/text content.
            for vector_rect, vector_obj in page_vectors:
                for text_rect, _text in text_spans:
                    if _overlap_ratio(vector_rect, text_rect) >= 0.10:
                        warnings.append({
                            "type": "vector_text_overlap",
                            "page": page_index + 1,
                            "object_id": vector_obj["id"],
                            "message": "يتداخل الرسم المتجهي مع نص؛ لا تحذفه قبل مراجعة المنطقة.",
                        })
                        break
                for image_rect, image_obj in page_images:
                    if _overlap_ratio(vector_rect, image_rect) >= 0.10:
                        warnings.append({
                            "type": "vector_image_overlap",
                            "page": page_index + 1,
                            "object_id": vector_obj["id"],
                            "other_object_id": image_obj["id"],
                            "message": "يتداخل الرسم المتجهي مع صورة؛ راجع الطبقات قبل التعديل.",
                        })
                        break
            for vector_index, (vector_rect, vector_obj) in enumerate(page_vectors):
                for other_rect, other_obj in page_vectors[vector_index + 1:]:
                    if _overlap_ratio(vector_rect, other_rect) >= 0.10:
                        warnings.append({
                            "type": "vector_vector_overlap",
                            "page": page_index + 1,
                            "object_id": vector_obj["id"],
                            "other_object_id": other_obj["id"],
                            "message": "يتداخل هذا الرسم مع رسم متجهي آخر؛ قد يكونان جزءًا من شكل مركب.",
                        })

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




MAX_TEXT_EDIT_CHARS = 240


def replace_isolated_latin_pdf_text(data: bytes, operation: dict[str, Any]) -> bytes:
    """Replace one isolated horizontal Latin span; retain baseline, size, and color."""
    if not isinstance(operation, dict) or operation.get("action") != "replace":
        raise ValueError("عملية استبدال النص غير صالحة.")
    replacement = operation.get("replacement")
    if not isinstance(replacement, str) or not replacement.strip() or len(replacement) > MAX_TEXT_EDIT_CHARS:
        raise ValueError("اكتب نصًا بديلًا من 1 إلى 240 حرفًا.")
    replacement = replacement.strip()
    if any(ord(ch) > 0x024F or ord(ch) < 32 for ch in replacement):
        raise ValueError("هذه المرحلة تدعم الحروف اللاتينية فقط؛ دعم العربية قيد التطوير لضمان سلامة تشكيل الحروف.")
    try:
        page_number = int(operation["page"])
        object_id = str(operation["object_id"])
        text_hash = str(operation["text_hash"])
        coords = operation["rect"]
        if not isinstance(coords, list) or len(coords) != 4:
            raise ValueError
        normalized = [float(v) for v in coords]
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("بيانات النص أو إحداثياته غير صالحة.") from exc
    if not all(math.isfinite(v) for v in normalized) or not re.fullmatch(r"[0-9a-f]{64}", text_hash):
        raise ValueError("بصمة النص أو الإحداثيات غير صالحة؛ أعد الفهرسة.")
    if not 1 <= page_number <= 200 or not re.fullmatch(rf"p{page_number}-text-[0-9]+", object_id):
        raise ValueError("مرجع النص غير صالح.")
    x0, y0, x1, y1 = normalized
    if x0 < 0 or y0 < 0 or x1 > 1 or y1 > 1 or x1 <= x0 or y1 <= y0:
        raise ValueError("مستطيل النص يجب أن يقع داخل الصفحة.")
    doc = _open(data)
    try:
        if page_number > doc.page_count:
            raise ValueError("الصفحة المحددة خارج نطاق الملف.")
        page = doc.load_page(page_number - 1)
        page_rect = page.rect
        span_index = int(object_id.rsplit("-", 1)[1]) - 1
        spans = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    value = str(span.get("text", "")).strip()
                    if value:
                        spans.append((pymupdf.Rect(span.get("bbox", (0,0,0,0))),
                                      {**span, "text": value, "direction": line.get("dir", (1,0))}))
        if not 0 <= span_index < len(spans):
            raise ValueError("لم يتم العثور على النص؛ أعد فهرسة الملف.")
        target_rect, target = spans[span_index]
        original = target["text"]
        if len(original) > MAX_TEXT_EDIT_CHARS or hashlib.sha256(original.encode("utf-8")).hexdigest() != text_hash:
            raise ValueError("تغيّر النص أو تجاوز الحد؛ أعد فهرسة الملف.")
        direction = target["direction"]
        if any(ord(ch) > 0x024F for ch in original) or abs(float(direction[1])) > 0.01 or float(direction[0]) < 0:
            raise ValueError("هذا المقطع ليس نصًا لاتينيًا أفقيًا بسيطًا.")
        supplied = pymupdf.Rect(page_rect.x0+x0*page_rect.width, page_rect.y0+y0*page_rect.height,
                                page_rect.x0+x1*page_rect.width, page_rect.y0+y1*page_rect.height)
        if any(abs(a-b) > 1.5 for a,b in zip(target_rect, supplied)):
            raise ValueError("موضع النص تغيّر؛ أعد فهرسة الملف.")
        for index, (other_rect, _) in enumerate(spans):
            if index != span_index and _overlap_ratio(target_rect, other_rect) > 0:
                raise ValueError("يتداخل النص مع مقطع آخر؛ لن يتم استبداله.")
        for info in page.get_image_info(xrefs=True):
            if _overlap_ratio(target_rect, pymupdf.Rect(info.get("bbox", (0,0,0,0)))) > 0:
                raise ValueError("يتداخل النص مع صورة؛ لن يتم استبداله.")
        for drawing in page.get_drawings():
            if drawing.get("rect") and _overlap_ratio(target_rect, pymupdf.Rect(drawing["rect"])) > 0:
                raise ValueError("يتداخل النص مع رسم؛ لن يتم استبداله.")
        for annotation in page.annots() or []:
            if _overlap_ratio(target_rect, pymupdf.Rect(annotation.rect)) > 0:
                raise ValueError("يتداخل النص مع تعليق؛ لن يتم استبداله.")
        font_name = str(target.get("font") or "")
        font_alias, font_buffer = "helv", None
        for entry in page.get_fonts(full=True):
            xref, _ext, _kind, basefont, resource_name, _encoding, *_ = entry
            if str(basefont).lstrip("/+").split("+")[-1] == font_name or resource_name == font_name:
                if xref > 0:
                    extracted = doc.extract_font(xref)
                    if extracted and extracted[3]:
                        font_buffer = extracted[3]
                        font_alias = "AlfalqiReplaceFont"
                        page.insert_font(fontname=font_alias, fontbuffer=font_buffer)
                break
        if font_buffer:
            font = pymupdf.Font(fontbuffer=font_buffer)
        else:
            lowered = font_name.lower()
            if "courier" in lowered:
                font_alias = "cour"
            elif "times" in lowered:
                font_alias = "tiro"
            elif "helvetica" in lowered or "arial" in lowered or not lowered:
                font_alias = "helv"
            else:
                raise ValueError("تعذّر استخراج الخط الأصلي؛ لن نستخدم خطًا بديلًا قد يغيّر التنسيق.")
            font = pymupdf.Font(fontname=font_alias)
        fontsize = max(4.0, min(72.0, float(target.get("size") or 11)))
        if font.text_length(replacement, fontsize=fontsize) > target_rect.width + 0.5:
            raise ValueError("النص البديل أعرض من المساحة الأصلية؛ اختصره للحفاظ على التخطيط.")
        color_int = int(target.get("color") or 0)
        color = (((color_int>>16)&255)/255, ((color_int>>8)&255)/255, (color_int&255)/255)
        origin = target.get("origin") or (target_rect.x0, target_rect.y1-font.ascender*fontsize)
        expected = [span["text"] for index, (_rect, span) in enumerate(spans) if index != span_index]
        page.add_redact_annot(target_rect, fill=None, cross_out=False)
        page.apply_redactions(images=0, graphics=0, text=0)
        page.insert_text((float(origin[0]), float(origin[1])), replacement,
                         fontname=font_alias, fontsize=fontsize, color=color, overlay=True)
        after = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    value = str(span.get("text", "")).strip()
                    if value:
                        after.append(value)
        import unicodedata
        normalize_text = lambda value: unicodedata.normalize("NFKC", value).replace("\u200e", "").replace("\u200f", "").strip()
        normalized_after = normalize_text(" ".join(after))
        if not all(normalize_text(value) in normalized_after for value in expected) or normalize_text(replacement) not in normalized_after:
            raise ValueError("تعذّر التحقق من النص الناتج؛ أُلغي التعديل.")
        output = doc.tobytes(garbage=4, deflate=True, clean=True)
        if not output.startswith(b"%PDF-"):
            raise ValueError("تعذّر إنشاء النسخة المعدّلة.")
        return output
    finally:
        doc.close()


def replace_isolated_arabic_pdf_text(data: bytes, operation: dict[str, Any]) -> bytes:
    """Replace one isolated horizontal Arabic span using HarfBuzz-backed Story layout."""
    import html as html_lib

    if not isinstance(operation, dict) or operation.get("action") != "replace_ar":
        raise ValueError("عملية استبدال النص العربي غير صالحة.")
    replacement = operation.get("replacement")
    if not isinstance(replacement, str) or not replacement.strip() or len(replacement) > MAX_TEXT_EDIT_CHARS:
        raise ValueError("اكتب نصًا عربيًا بديلًا من 1 إلى 240 حرفًا.")
    replacement = replacement.strip()
    if not re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", replacement):
        raise ValueError("يجب أن يحتوي النص البديل على حروف عربية.")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in replacement):
        raise ValueError("النص البديل يحتوي على محارف غير مدعومة.")
    try:
        page_number = int(operation["page"])
        object_id = str(operation["object_id"])
        text_hash = str(operation["text_hash"])
        coords = operation["rect"]
        if not isinstance(coords, list) or len(coords) != 4:
            raise ValueError
        normalized = [float(v) for v in coords]
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("بيانات النص العربي أو إحداثياته غير صالحة.") from exc
    if not all(math.isfinite(v) for v in normalized) or not re.fullmatch(r"[0-9a-f]{64}", text_hash):
        raise ValueError("بصمة النص أو الإحداثيات غير صالحة؛ أعد الفهرسة.")
    if not 1 <= page_number <= 200 or not re.fullmatch(rf"p{page_number}-text-[0-9]+", object_id):
        raise ValueError("مرجع النص غير صالح.")
    x0, y0, x1, y1 = normalized
    if x0 < 0 or y0 < 0 or x1 > 1 or y1 > 1 or x1 <= x0 or y1 <= y0:
        raise ValueError("مستطيل النص يجب أن يقع داخل الصفحة.")
    doc = _open(data)
    try:
        if page_number > doc.page_count:
            raise ValueError("الصفحة المحددة خارج نطاق الملف.")
        page = doc.load_page(page_number - 1)
        page_rect = page.rect
        span_index = int(object_id.rsplit("-", 1)[1]) - 1
        spans = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    value = str(span.get("text", "")).strip()
                    if value:
                        spans.append((pymupdf.Rect(span.get("bbox", (0, 0, 0, 0))),
                                      {**span, "text": value, "direction": line.get("dir", (1, 0))}))
        if not 0 <= span_index < len(spans):
            raise ValueError("لم يتم العثور على النص العربي؛ أعد فهرسة الملف.")
        target_rect, target = spans[span_index]
        original = target["text"]
        if len(original) > MAX_TEXT_EDIT_CHARS or hashlib.sha256(original.encode("utf-8")).hexdigest() != text_hash:
            raise ValueError("تغيّر النص أو تجاوز الحد؛ أعد فهرسة الملف.")
        direction = target["direction"]
        import unicodedata
        normalized_original = unicodedata.normalize("NFKC", original)
        if not re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", normalized_original):
            raise ValueError("المقطع المحدد ليس نصًا عربيًا.")
        if abs(float(direction[1])) > 0.01:
            raise ValueError("يدعم الاستبدال حاليًا النص العربي الأفقي فقط؛ النص المائل أو العمودي غير مدعوم.")
        supplied = pymupdf.Rect(page_rect.x0+x0*page_rect.width, page_rect.y0+y0*page_rect.height,
                                page_rect.x0+x1*page_rect.width, page_rect.y0+y1*page_rect.height)
        if any(abs(a-b) > 1.5 for a, b in zip(target_rect, supplied)):
            raise ValueError("موضع النص تغيّر؛ أعد فهرسة الملف.")
        for index, (other_rect, _) in enumerate(spans):
            if index != span_index and _overlap_ratio(target_rect, other_rect) > 0:
                raise ValueError("يتداخل النص مع مقطع آخر؛ لن يتم استبداله.")
        for info in page.get_image_info(xrefs=True):
            if _overlap_ratio(target_rect, pymupdf.Rect(info.get("bbox", (0, 0, 0, 0)))) > 0:
                raise ValueError("يتداخل النص مع صورة؛ لن يتم استبداله.")
        for drawing in page.get_drawings():
            if drawing.get("rect") and _overlap_ratio(target_rect, pymupdf.Rect(drawing["rect"])) > 0:
                raise ValueError("يتداخل النص مع رسم؛ لن يتم استبداله.")
        for annotation in page.annots() or []:
            if _overlap_ratio(target_rect, pymupdf.Rect(annotation.rect)) > 0:
                raise ValueError("يتداخل النص مع تعليق؛ لن يتم استبداله.")
        fontsize = max(4.0, min(72.0, float(target.get("size") or 11)))
        color_int = int(target.get("color") or 0)
        color_hex = f"#{color_int:06X}"
        expected = [span["text"] for index, (_rect, span) in enumerate(spans) if index != span_index]
        page.add_redact_annot(target_rect, fill=None, cross_out=False)
        page.apply_redactions(images=0, graphics=0, text=0)
        safe_text = html_lib.escape(replacement).replace("\\n", "<br>")
        html = f'<div dir="rtl" style="font-family: Noto Naskh Arabic; font-size: {fontsize:.2f}pt; color: {color_hex}; text-align: right; direction: rtl; line-height: 1.15">{safe_text}</div>'
        try:
            spare_height, scale = page.insert_htmlbox(target_rect, html, css="div { margin: 0; padding: 0; }", scale_low=0.95)
        except Exception as exc:
            raise ValueError("تعذّر تشكيل النص العربي بالخط المتاح؛ لم يتم اعتماد التعديل.") from exc
        if spare_height < 0 or scale < 0.95:
            raise ValueError("النص العربي البديل لا يتسع في المساحة الأصلية؛ اختصره للحفاظ على التخطيط.")
        after = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    value = str(span.get("text", "")).strip()
                    if value:
                        after.append(value)
        from collections import Counter
        if Counter(after) != Counter(expected + [replacement]):
            raise ValueError("تعذّر التحقق من النص العربي الناتج؛ أُلغي التعديل.")
        output = doc.tobytes(garbage=4, deflate=True, clean=True)
        if not output.startswith(b"%PDF-"):
            raise ValueError("تعذّر إنشاء النسخة المعدّلة.")
        return output
    finally:
        doc.close()


def delete_isolated_pdf_text(data: bytes, operation: dict[str, Any]) -> bytes:
    """Delete one isolated, revalidated text span and verify no neighboring text changed."""
    if not isinstance(operation, dict) or operation.get("action") != "delete":
        raise ValueError("العملية المدعومة حاليًا هي حذف مقطع نصي منفصل فقط.")
    try:
        page_number = int(operation["page"])
        object_id = str(operation["object_id"])
        text_hash = str(operation["text_hash"])
        coords = operation["rect"]
        if not isinstance(coords, list) or len(coords) != 4:
            raise ValueError
        normalized = [float(value) for value in coords]
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("بيانات النص أو إحداثياته غير صالحة.") from exc
    if not all(math.isfinite(v) for v in normalized):
        raise ValueError("إحداثيات النص غير صالحة.")
    if not 1 <= page_number <= 200 or not re.fullmatch(r"p[0-9]+-text-[0-9]+", object_id):
        raise ValueError("مرجع النص غير صالح.")
    if len(text_hash) != 64 or not re.fullmatch(r"[0-9a-f]{64}", text_hash):
        raise ValueError("بصمة النص غير صالحة؛ أعد فهرسة الملف.")
    x0, y0, x1, y1 = normalized
    if x0 < 0 or y0 < 0 or x1 > 1 or y1 > 1 or x1 <= x0 or y1 <= y0:
        raise ValueError("مستطيل النص يجب أن يقع داخل الصفحة.")
    doc = _open(data)
    try:
        if page_number > doc.page_count or not object_id.startswith(f"p{page_number}-text-"):
            raise ValueError("مرجع النص خارج نطاق الملف.")
        page = doc.load_page(page_number - 1)
        page_rect = page.rect
        try:
            span_index = int(object_id.rsplit("-", 1)[1]) - 1
        except ValueError as exc:
            raise ValueError("معرّف النص غير صالح.") from exc
        spans: list[tuple[pymupdf.Rect, str]] = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    value = str(span.get("text", "")).strip()
                    if value:
                        spans.append((pymupdf.Rect(span.get("bbox", (0, 0, 0, 0))), value))
        if span_index < 0 or span_index >= len(spans):
            raise ValueError("لم يتم العثور على النص المحدد؛ أعد فهرسة الملف.")
        target_rect, target_text = spans[span_index]
        if len(target_text) > MAX_TEXT_EDIT_CHARS:
            raise ValueError("هذا المقطع أطول من الحد الآمن للحذف الفردي.")
        if hashlib.sha256(target_text.encode("utf-8")).hexdigest() != text_hash:
            raise ValueError("تغيّر النص؛ أعد فهرسة الملف قبل التعديل.")
        supplied = pymupdf.Rect(page_rect.x0 + x0 * page_rect.width,
                                page_rect.y0 + y0 * page_rect.height,
                                page_rect.x0 + x1 * page_rect.width,
                                page_rect.y0 + y1 * page_rect.height)
        if any(abs(a-b) > 1.5 for a,b in zip(target_rect, supplied)):
            raise ValueError("تغيّر موضع النص؛ أعد فهرسة الملف قبل التعديل.")
        # Redaction rectangles can affect neighboring content. Reject any overlap
        # with another text span, image, vector path or annotation before proceeding.
        for index, (other_rect, _value) in enumerate(spans):
            if index != span_index and _overlap_ratio(target_rect, other_rect) > 0:
                raise ValueError("يتداخل النص مع مقطع نصي آخر؛ لن يتم حذفه لتجنب إتلاف المحتوى.")
        for info in page.get_image_info(xrefs=True):
            if _overlap_ratio(target_rect, pymupdf.Rect(info.get("bbox", (0,0,0,0)))) > 0:
                raise ValueError("يتداخل النص مع صورة؛ لن يتم حذفه.")
        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if rect and _overlap_ratio(target_rect, pymupdf.Rect(rect)) > 0:
                raise ValueError("يتداخل النص مع رسم متجهي؛ لن يتم حذفه.")
        for annotation in page.annots() or []:
            if _overlap_ratio(target_rect, pymupdf.Rect(annotation.rect)) > 0:
                raise ValueError("يتداخل النص مع تعليق؛ لن يتم حذفه.")
        expected = [value for index, (_rect, value) in enumerate(spans) if index != span_index]
        page.add_redact_annot(target_rect, fill=None, cross_out=False)
        page.apply_redactions(images=0, graphics=0, text=0)
        after: list[str] = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    value = str(span.get("text", "")).strip()
                    if value:
                        after.append(value)
        if after != expected:
            raise ValueError("تعذّر ضمان بقاء النصوص المجاورة كما هي؛ أُلغي التعديل.")
        output = doc.tobytes(garbage=4, deflate=True, clean=True)
        if not output.startswith(b"%PDF-"):
            raise ValueError("تعذّر إنشاء نسخة PDF المعدّلة.")
        return output
    finally:
        doc.close()


MAX_VECTOR_EDIT_OPS = 20






def move_isolated_pdf_vector(data: bytes, operation: dict[str, Any]) -> bytes:
    """Move an isolated single rectangle or line by a bounded point offset."""
    if not isinstance(operation,dict) or operation.get("action")!="move":
        raise ValueError("عملية نقل الرسم غير صالحة.")
    try:
        page_number=int(operation["page"])
        object_id=str(operation["object_id"])
        coords=operation["rect"]
        if not isinstance(coords,list) or len(coords)!=4: raise ValueError
        normalized=[float(v) for v in coords]
        dx=float(operation["dx"]); dy=float(operation["dy"])
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        raise ValueError("بيانات نقل الرسم غير صالحة.") from exc
    if not math.isfinite(dx) or not math.isfinite(dy) or abs(dx)>500 or abs(dy)>500:
        raise ValueError("الإزاحة يجب أن تكون بين -500 و500 نقطة.")
    if not 1<=page_number<=200 or not re.fullmatch(rf"p{page_number}-vector-[0-9]+",object_id):
        raise ValueError("مرجع الرسم غير صالح.")
    if not all(math.isfinite(v) for v in normalized):
        raise ValueError("إحداثيات الرسم غير صالحة.")
    x0,y0,x1,y1=normalized
    if x0<0 or y0<0 or x1>1 or y1>1 or x1<=x0 or y1<=y0:
        raise ValueError("مستطيل الرسم يجب أن يقع داخل الصفحة.")
    doc=_open(data)
    try:
        if page_number>doc.page_count: raise ValueError("الصفحة المحددة خارج نطاق الملف.")
        page=doc.load_page(page_number-1); drawings=page.get_drawings()
        index=int(object_id.rsplit("-",1)[1])-1
        if not 0<=index<len(drawings): raise ValueError("لم يتم العثور على الرسم؛ أعد الفهرسة.")
        drawing=drawings[index]; items=drawing.get("items",[])
        if len(items)!=1 or items[0][0] not in {"re","l"}:
            raise ValueError("يدعم النقل حاليًا المستطيل والخط المستقيم المنفرد فقط.")
        old_rect=pymupdf.Rect(drawing.get("rect") or (0,0,0,0)); page_rect=page.rect
        supplied=pymupdf.Rect(page_rect.x0+x0*page_rect.width,page_rect.y0+y0*page_rect.height,
                              page_rect.x0+x1*page_rect.width,page_rect.y0+y1*page_rect.height)
        if any(abs(a-b)>1.5 for a,b in zip(old_rect,supplied)):
            raise ValueError("تغيّر موضع الرسم؛ أعد الفهرسة.")
        new_rect=old_rect+ (dx,dy,dx,dy)
        if not page_rect.contains(new_rect): raise ValueError("الموضع الجديد يتجاوز حدود الصفحة.")
        for block in page.get_text("dict").get("blocks",[]):
            if block.get("type")!=0: continue
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    text_rect=pymupdf.Rect(span.get("bbox",(0,0,0,0)))
                    if old_rect.intersects(text_rect): raise ValueError("الرسم الأصلي يتداخل مع نص.")
                    if new_rect.intersects(text_rect): raise ValueError("الموضع الجديد سيتداخل مع نص.")
        for info in page.get_image_info(xrefs=True):
            image_rect=pymupdf.Rect(info.get("bbox",(0,0,0,0)))
            if old_rect.intersects(image_rect): raise ValueError("الرسم الأصلي يتداخل مع صورة.")
            if new_rect.intersects(image_rect): raise ValueError("الموضع الجديد سيتداخل مع صورة.")
        for other_index,other in enumerate(drawings):
            if other_index==index: continue
            other_rect=pymupdf.Rect(other.get("rect") or (0,0,0,0))
            if old_rect.intersects(other_rect): raise ValueError("الرسم الأصلي يتداخل مع رسم آخر.")
            if new_rect.intersects(other_rect): raise ValueError("الموضع الجديد سيتداخل مع رسم آخر.")
        for annotation in page.annots() or []:
            ann_rect=pymupdf.Rect(annotation.rect)
            if old_rect.intersects(ann_rect): raise ValueError("الرسم الأصلي يتداخل مع تعليق.")
            if new_rect.intersects(ann_rect): raise ValueError("الموضع الجديد سيتداخل مع تعليق.")
        stroke=tuple(drawing["color"]) if drawing.get("color") else None
        fill=tuple(drawing["fill"]) if drawing.get("fill") else None
        width=max(0.1,min(20.0,float(drawing.get("width") or 1)))
        caps=drawing.get("lineCap") or (0,0,0); cap=int(caps[0] if isinstance(caps,(list,tuple)) else caps)
        common={"color":stroke,"width":width,"dashes":drawing.get("dashes") or "[] 0","lineCap":cap,
                "lineJoin":int(float(drawing.get("lineJoin") or 0)),
                "stroke_opacity":float(drawing.get("stroke_opacity") or 1),"overlay":True}
        page.add_redact_annot(old_rect,fill=None,cross_out=False)
        page.apply_redactions(images=0,graphics=2,text=0)
        if items[0][0]=="re":
            page.draw_rect(pymupdf.Rect(items[0][1])+ (dx,dy,dx,dy),fill=fill,
                           fill_opacity=float(drawing.get("fill_opacity") or 1),**common)
        else:
            page.draw_line(items[0][1]+(dx,dy),items[0][2]+(dx,dy),**common)
        output=doc.tobytes(garbage=4,deflate=True,clean=True)
        if not output.startswith(b"%PDF-"): raise ValueError("تعذّر إنشاء النسخة المعدّلة.")
        return output
    finally:
        doc.close()

def restyle_isolated_pdf_vector(data: bytes, operation: dict[str, Any]) -> bytes:
    """Change stroke width and opacity of an isolated rectangle or straight line."""
    if not isinstance(operation, dict) or operation.get("action") != "restyle":
        raise ValueError("عملية تنسيق الرسم غير صالحة.")
    try:
        page_number=int(operation["page"])
        object_id=str(operation["object_id"])
        coords=operation["rect"]
        if not isinstance(coords,list) or len(coords)!=4:
            raise ValueError
        normalized=[float(v) for v in coords]
        width=float(operation.get("line_width"))
        opacity=float(operation.get("opacity",1))
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        raise ValueError("بيانات تنسيق الرسم غير صالحة.") from exc
    if not math.isfinite(width) or not 0.1<=width<=20:
        raise ValueError("سماكة الخط يجب أن تكون بين 0.1 و20 نقطة.")
    if not math.isfinite(opacity) or not 0<=opacity<=1:
        raise ValueError("الشفافية يجب أن تكون بين 0 و1.")
    if not 1<=page_number<=200 or not re.fullmatch(rf"p{page_number}-vector-[0-9]+",object_id):
        raise ValueError("مرجع الرسم غير صالح.")
    if not all(math.isfinite(v) for v in normalized):
        raise ValueError("إحداثيات الرسم غير صالحة.")
    x0,y0,x1,y1=normalized
    if x0<0 or y0<0 or x1>1 or y1>1 or x1<=x0 or y1<=y0:
        raise ValueError("مستطيل الرسم يجب أن يقع داخل الصفحة.")
    doc=_open(data)
    try:
        if page_number>doc.page_count:
            raise ValueError("الصفحة المحددة خارج نطاق الملف.")
        page=doc.load_page(page_number-1)
        drawings=page.get_drawings()
        index=int(object_id.rsplit("-",1)[1])-1
        if not 0<=index<len(drawings):
            raise ValueError("لم يتم العثور على الرسم؛ أعد الفهرسة.")
        drawing=drawings[index]
        items=drawing.get("items",[])
        if len(items)!=1 or items[0][0] not in {"re","l"}:
            raise ValueError("يدعم تنسيق الرسم حاليًا المستطيل والخط المستقيم المنفرد فقط.")
        old_rect=pymupdf.Rect(drawing.get("rect") or (0,0,0,0))
        page_rect=page.rect
        supplied=pymupdf.Rect(page_rect.x0+x0*page_rect.width,page_rect.y0+y0*page_rect.height,
                              page_rect.x0+x1*page_rect.width,page_rect.y0+y1*page_rect.height)
        if any(abs(a-b)>1.5 for a,b in zip(old_rect,supplied)):
            raise ValueError("تغيّر موضع الرسم؛ أعد الفهرسة.")
        for block in page.get_text("dict").get("blocks",[]):
            if block.get("type")!=0: continue
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    if old_rect.intersects(pymupdf.Rect(span.get("bbox",(0,0,0,0)))):
                        raise ValueError("الرسم يتداخل مع نص؛ لن يتم تعديل تنسيقه.")
        for info in page.get_image_info(xrefs=True):
            if old_rect.intersects(pymupdf.Rect(info.get("bbox",(0,0,0,0)))):
                raise ValueError("الرسم يتداخل مع صورة؛ لن يتم تعديل تنسيقه.")
        for other_index,other in enumerate(drawings):
            if other_index!=index and old_rect.intersects(pymupdf.Rect(other.get("rect") or (0,0,0,0))):
                raise ValueError("الرسم يتداخل مع رسم آخر؛ لن يتم تعديل تنسيقه.")
        for annotation in page.annots() or []:
            if old_rect.intersects(pymupdf.Rect(annotation.rect)):
                raise ValueError("الرسم يتداخل مع تعليق؛ لن يتم تعديل تنسيقه.")
        stroke=tuple(drawing["color"]) if drawing.get("color") else None
        fill=tuple(drawing["fill"]) if drawing.get("fill") else None
        if stroke is None:
            raise ValueError("هذا الرسم لا يحتوي على حد يمكن تغيير سماكته.")
        caps=drawing.get("lineCap") or (0,0,0)
        cap=int(caps[0] if isinstance(caps,(list,tuple)) else caps)
        dashes=drawing.get("dashes") or "[] 0"
        join=int(float(drawing.get("lineJoin") or 0))
        page.add_redact_annot(old_rect,fill=None,cross_out=False)
        page.apply_redactions(images=0,graphics=2,text=0)
        if items[0][0]=="re":
            page.draw_rect(pymupdf.Rect(items[0][1]),color=stroke,fill=fill,width=width,dashes=dashes,
                           lineCap=cap,lineJoin=join,stroke_opacity=opacity,
                           fill_opacity=float(drawing.get("fill_opacity") or 1),overlay=True)
        else:
            page.draw_line(items[0][1],items[0][2],color=stroke,width=width,dashes=dashes,
                           lineCap=cap,lineJoin=join,stroke_opacity=opacity,overlay=True)
        output=doc.tobytes(garbage=4,deflate=True,clean=True)
        if not output.startswith(b"%PDF-"):
            raise ValueError("تعذّر إنشاء النسخة المعدّلة.")
        return output
    finally:
        doc.close()

def scale_isolated_pdf_vector(data: bytes, operation: dict[str, Any]) -> bytes:
    """Scale an isolated single rectangle or straight line around its center."""
    if not isinstance(operation, dict) or operation.get("action") != "scale":
        raise ValueError("عملية تغيير حجم الرسم غير صالحة.")
    try:
        page_number=int(operation["page"])
        object_id=str(operation["object_id"])
        coords=operation["rect"]
        if not isinstance(coords,list) or len(coords)!=4:
            raise ValueError
        normalized=[float(v) for v in coords]
        scale=float(operation["scale"])
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        raise ValueError("بيانات الرسم أو نسبة الحجم غير صالحة.") from exc
    if not math.isfinite(scale) or not 0.5<=scale<=2:
        raise ValueError("نسبة تغيير الحجم يجب أن تكون بين 50% و200%.")
    if not 1<=page_number<=200 or not re.fullmatch(rf"p{page_number}-vector-[0-9]+",object_id):
        raise ValueError("مرجع الرسم غير صالح.")
    if not all(math.isfinite(v) for v in normalized):
        raise ValueError("إحداثيات الرسم غير صالحة.")
    x0,y0,x1,y1=normalized
    if x0<0 or y0<0 or x1>1 or y1>1 or x1<=x0 or y1<=y0:
        raise ValueError("مستطيل الرسم يجب أن يقع داخل الصفحة.")
    doc=_open(data)
    try:
        if page_number>doc.page_count:
            raise ValueError("الصفحة المحددة خارج نطاق الملف.")
        page=doc.load_page(page_number-1)
        drawings=page.get_drawings()
        index=int(object_id.rsplit("-",1)[1])-1
        if not 0<=index<len(drawings):
            raise ValueError("لم يتم العثور على الرسم؛ أعد الفهرسة.")
        drawing=drawings[index]
        items=drawing.get("items",[])
        if len(items)!=1 or items[0][0] not in {"re","l"}:
            raise ValueError("يدعم تغيير الحجم حاليًا المستطيل والخط المستقيم المنفرد فقط.")
        old_rect=pymupdf.Rect(drawing.get("rect") or (0,0,0,0))
        page_rect=page.rect
        supplied=pymupdf.Rect(page_rect.x0+x0*page_rect.width,page_rect.y0+y0*page_rect.height,
                              page_rect.x0+x1*page_rect.width,page_rect.y0+y1*page_rect.height)
        if any(abs(a-b)>1.5 for a,b in zip(old_rect,supplied)):
            raise ValueError("تغيّر موضع الرسم؛ أعد فهرسة الملف.")
        center=old_rect.tl+(old_rect.br-old_rect.tl)*0.5
        new_rect=pymupdf.Rect(center.x-old_rect.width*scale/2,center.y-old_rect.height*scale/2,
                              center.x+old_rect.width*scale/2,center.y+old_rect.height*scale/2)
        if not page_rect.contains(new_rect):
            raise ValueError("الحجم الجديد يتجاوز حدود الصفحة.")
        for block in page.get_text("dict").get("blocks",[]):
            if block.get("type")!=0: continue
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    text_rect=pymupdf.Rect(span.get("bbox",(0,0,0,0)))
                    if old_rect.intersects(text_rect):
                        raise ValueError("الرسم الأصلي يتداخل مع نص؛ لم يتم التعديل.")
                    if new_rect.intersects(text_rect):
                        raise ValueError("الحجم الجديد سيتداخل مع نص؛ لم يتم التعديل.")
        for info in page.get_image_info(xrefs=True):
            image_rect=pymupdf.Rect(info.get("bbox",(0,0,0,0)))
            if old_rect.intersects(image_rect):
                raise ValueError("الرسم الأصلي يتداخل مع صورة؛ لم يتم التعديل.")
            if new_rect.intersects(image_rect):
                raise ValueError("الحجم الجديد سيتداخل مع صورة؛ لم يتم التعديل.")
        for other_index,other in enumerate(drawings):
            if other_index==index: continue
            other_rect=pymupdf.Rect(other.get("rect") or (0,0,0,0))
            if old_rect.intersects(other_rect):
                raise ValueError("الرسم الأصلي يتداخل مع رسم آخر؛ لم يتم التعديل.")
            if new_rect.intersects(other_rect):
                raise ValueError("الحجم الجديد سيتداخل مع رسم آخر؛ لم يتم التعديل.")
        for annotation in page.annots() or []:
            annotation_rect=pymupdf.Rect(annotation.rect)
            if old_rect.intersects(annotation_rect):
                raise ValueError("الرسم الأصلي يتداخل مع تعليق؛ لم يتم التعديل.")
            if new_rect.intersects(annotation_rect):
                raise ValueError("الحجم الجديد سيتداخل مع تعليق؛ لم يتم التعديل.")
        stroke=tuple(drawing["color"]) if drawing.get("color") else None
        fill=tuple(drawing["fill"]) if drawing.get("fill") else None
        width=max(0.1,min(20.0,float(drawing.get("width") or 1)))
        caps=drawing.get("lineCap") or (0,0,0)
        cap=int(caps[0] if isinstance(caps,(list,tuple)) else caps)
        common={"width":width,"dashes":drawing.get("dashes") or "[] 0",
                "lineCap":cap,"lineJoin":int(float(drawing.get("lineJoin") or 0)),
                "stroke_opacity":float(drawing.get("stroke_opacity") or 1),"overlay":True}
        page.add_redact_annot(old_rect,fill=None,cross_out=False)
        page.apply_redactions(images=0,graphics=2,text=0)
        if items[0][0]=="re":
            page.draw_rect(new_rect,color=stroke,fill=fill,fill_opacity=float(drawing.get("fill_opacity") or 1),**common)
        else:
            p1,p2=items[0][1],items[0][2]
            new_p1=pymupdf.Point(center.x+(p1.x-center.x)*scale,center.y+(p1.y-center.y)*scale)
            new_p2=pymupdf.Point(center.x+(p2.x-center.x)*scale,center.y+(p2.y-center.y)*scale)
            page.draw_line(new_p1,new_p2,color=stroke,**common)
        output=doc.tobytes(garbage=4,deflate=True,clean=True)
        if not output.startswith(b"%PDF-"):
            raise ValueError("تعذّر إنشاء النسخة المعدّلة.")
        return output
    finally:
        doc.close()

def recolor_isolated_pdf_vector(data: bytes, operation: dict[str, Any]) -> bytes:
    """Recolor an isolated single rectangle or line without changing its geometry."""
    if not isinstance(operation, dict) or operation.get("action") != "recolor":
        raise ValueError("عملية تغيير لون الرسم غير صالحة.")
    def parse_color(value, label):
        if value is None or value == "":
            return None
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError(f"لون {label} يجب أن يكون بصيغة #RRGGBB.")
        return tuple(int(value[i:i+2], 16)/255 for i in (1,3,5))
    stroke_color = parse_color(operation.get("stroke_color"), "الحد")
    fill_color = parse_color(operation.get("fill_color"), "التعبئة")
    if stroke_color is None and fill_color is None:
        raise ValueError("حدد لون الحد أو لون التعبئة على الأقل.")
    try:
        page_number = int(operation["page"])
        object_id = str(operation["object_id"])
        coords = operation["rect"]
        if not isinstance(coords, list) or len(coords) != 4:
            raise ValueError
        normalized = [float(v) for v in coords]
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("بيانات الرسم أو إحداثياته غير صالحة.") from exc
    if not 1 <= page_number <= 200 or not re.fullmatch(rf"p{page_number}-vector-[0-9]+", object_id):
        raise ValueError("مرجع الرسم غير صالح.")
    if not all(math.isfinite(v) for v in normalized):
        raise ValueError("إحداثيات الرسم غير صالحة.")
    x0,y0,x1,y1=normalized
    if x0<0 or y0<0 or x1>1 or y1>1 or x1<=x0 or y1<=y0:
        raise ValueError("مستطيل الرسم يجب أن يقع داخل الصفحة.")
    doc=_open(data)
    try:
        if page_number>doc.page_count:
            raise ValueError("الصفحة المحددة خارج نطاق الملف.")
        page=doc.load_page(page_number-1)
        drawings=page.get_drawings()
        index=int(object_id.rsplit("-",1)[1])-1
        if not 0<=index<len(drawings):
            raise ValueError("لم يتم العثور على الرسم؛ أعد الفهرسة.")
        drawing=drawings[index]
        rect=pymupdf.Rect(drawing.get("rect") or (0,0,0,0))
        page_rect=page.rect
        supplied=pymupdf.Rect(page_rect.x0+x0*page_rect.width,page_rect.y0+y0*page_rect.height,
                              page_rect.x0+x1*page_rect.width,page_rect.y0+y1*page_rect.height)
        if any(abs(a-b)>1.5 for a,b in zip(rect,supplied)):
            raise ValueError("تغيّر موضع الرسم؛ أعد فهرسة الملف.")
        items=drawing.get("items",[])
        if len(items)!=1 or items[0][0] not in {"re","l"}:
            raise ValueError("يدعم تغيير اللون حاليًا المستطيل والخط المستقيم المنفرد فقط.")
        if stroke_color is not None and not drawing.get("color"):
            raise ValueError("هذا الرسم لا يحتوي على حد يمكن تغيير لونه.")
        if fill_color is not None and not drawing.get("fill"):
            raise ValueError("هذا الرسم لا يحتوي على تعبئة يمكن تغيير لونها.")
        for block in page.get_text("dict").get("blocks",[]):
            if block.get("type")!=0: continue
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    if rect.intersects(pymupdf.Rect(span.get("bbox",(0,0,0,0)))):
                        raise ValueError("الرسم يتداخل مع نص؛ لن يتم تغيير لونه.")
        for info in page.get_image_info(xrefs=True):
            if rect.intersects(pymupdf.Rect(info.get("bbox",(0,0,0,0)))):
                raise ValueError("الرسم يتداخل مع صورة؛ لن يتم تغيير لونه.")
        for other_index,other in enumerate(drawings):
            if other_index!=index and rect.intersects(pymupdf.Rect(other.get("rect") or (0,0,0,0))):
                raise ValueError("الرسم يتداخل مع رسم آخر؛ لن يتم تغيير لونه.")
        for annotation in page.annots() or []:
            if rect.intersects(pymupdf.Rect(annotation.rect)):
                raise ValueError("الرسم يتداخل مع تعليق؛ لن يتم تغيير لونه.")
        item=items[0]
        old_stroke=tuple(drawing["color"]) if drawing.get("color") else None
        old_fill=tuple(drawing["fill"]) if drawing.get("fill") else None
        new_stroke=stroke_color if stroke_color is not None else old_stroke
        new_fill=fill_color if fill_color is not None else old_fill
        width=max(0.1,min(20.0,float(drawing.get("width") or 1)))
        stroke_opacity=float(drawing.get("stroke_opacity") or 1)
        fill_opacity=float(drawing.get("fill_opacity") or 1)
        dashes=drawing.get("dashes") or "[] 0"
        line_caps=drawing.get("lineCap") or (0,0,0)
        line_cap=int(line_caps[0] if isinstance(line_caps,(list,tuple)) else line_caps)
        line_join=int(float(drawing.get("lineJoin") or 0))
        page.add_redact_annot(rect,fill=None,cross_out=False)
        page.apply_redactions(images=0,graphics=2,text=0)
        if item[0]=="re":
            shape_rect=pymupdf.Rect(item[1])
            page.draw_rect(shape_rect,color=new_stroke,fill=new_fill,width=width,
                           dashes=dashes,lineCap=line_cap,lineJoin=line_join,
                           stroke_opacity=stroke_opacity,fill_opacity=fill_opacity,overlay=True)
        else:
            page.draw_line(item[1],item[2],color=new_stroke,width=width,dashes=dashes,
                           lineCap=line_cap,lineJoin=line_join,stroke_opacity=stroke_opacity,overlay=True)
        output=doc.tobytes(garbage=4,deflate=True,clean=True)
        if not output.startswith(b"%PDF-"):
            raise ValueError("تعذّر إنشاء النسخة المعدّلة.")
        return output
    finally:
        doc.close()

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
            page.apply_redactions(images=0, graphics=2, text=0)

        output = doc.tobytes(garbage=4, deflate=True, clean=True)
        if not output.startswith(b"%PDF-"):
            raise ValueError("تعذّر إنشاء نسخة PDF المعدّلة.")
        return output
    finally:
        doc.close()
