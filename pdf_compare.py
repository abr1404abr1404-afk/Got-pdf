"""Page-by-page PDF comparison with bounded text extraction and safe summaries."""
from __future__ import annotations

import difflib
import math
from typing import Any

import pymupdf
from PIL import Image, ImageChops

MAX_COMPARE_PAGES = 30
MAX_TEXT_CHARS_PER_PAGE = 100_000
MAX_LINES_PER_PAGE = 3_000
MAX_DIFF_LINES = 80
MAX_VISUAL_PIXELS = 1_500_000
VISUAL_CHANGE_THRESHOLD = 24


def _open_pdf(data: bytes, label: str):
    if not data:
        raise ValueError(f"ملف {label} فارغ.")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"ملف {label} ليس PDF صالحًا.") from exc
    if doc.needs_pass:
        doc.close()
        raise ValueError(f"ملف {label} محمي بكلمة مرور. أزل الحماية قبل المقارنة.")
    if doc.page_count < 1 or doc.page_count > MAX_COMPARE_PAGES:
        count = doc.page_count
        doc.close()
        raise ValueError(f"ملف {label}: عدد الصفحات يجب أن يكون بين 1 و{MAX_COMPARE_PAGES} (الملف يحتوي {count}).")
    return doc


def _page_text(page) -> str:
    text = page.get_text("text", sort=True) or ""
    return text[:MAX_TEXT_CHARS_PER_PAGE]


def _line_diff(before: str, after: str) -> dict[str, Any]:
    old_all = before.splitlines()
    new_all = after.splitlines()
    old_lines = old_all[:MAX_LINES_PER_PAGE]
    new_lines = new_all[:MAX_LINES_PER_PAGE]
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    added: list[str] = []
    removed: list[str] = []
    changed_blocks = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed_blocks += 1
        if tag in ("delete", "replace"):
            removed.extend(old_lines[i1:i2])
        if tag in ("insert", "replace"):
            added.extend(new_lines[j1:j2])
    return {
        "added_lines": added[:MAX_DIFF_LINES],
        "removed_lines": removed[:MAX_DIFF_LINES],
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_blocks": changed_blocks,
        "truncated": (
            len(added) > MAX_DIFF_LINES
            or len(removed) > MAX_DIFF_LINES
            or len(old_all) > MAX_LINES_PER_PAGE
            or len(new_all) > MAX_LINES_PER_PAGE
        ),
        "compared_original_lines": len(old_lines),
        "compared_revised_lines": len(new_lines),
        "original_lines_truncated": len(old_all) > MAX_LINES_PER_PAGE,
        "revised_lines_truncated": len(new_all) > MAX_LINES_PER_PAGE,
    }



def _render_page(page) -> Image.Image:
    rect = page.rect
    width = max(1, int(math.ceil(rect.width)))
    height = max(1, int(math.ceil(rect.height)))
    scale = min(1.0, math.sqrt(MAX_VISUAL_PIXELS / (width * height)))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, colorspace=pymupdf.csRGB)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _visual_diff(before: Image.Image, after: Image.Image) -> dict[str, Any]:
    if before.size != after.size:
        return {"comparable": False, "changed": None, "changed_percent": None, "changed_bounds_px": None}
    difference = ImageChops.difference(before, after).convert("L")
    mask = difference.point(lambda value: 255 if value >= VISUAL_CHANGE_THRESHOLD else 0)
    changed_pixels = mask.histogram()[255]
    total_pixels = before.width * before.height
    bounds = mask.getbbox()
    return {
        "comparable": True,
        "changed": changed_pixels > 0,
        "changed_pixels": changed_pixels,
        "total_pixels": total_pixels,
        "changed_percent": round((changed_pixels / total_pixels) * 100, 3),
        "changed_bounds_px": list(bounds) if bounds else None,
    }

def compare_pdf_bytes(original: bytes, revised: bytes) -> dict[str, Any]:
    """Compare text, page geometry, and rendered appearance without changing sources."""
    first = _open_pdf(original, "الأصلي")
    second = _open_pdf(revised, "المعدّل")
    try:
        total = max(first.page_count, second.page_count)
        pages: list[dict[str, Any]] = []
        changed_pages = 0
        for index in range(total):
            if index >= first.page_count:
                pages.append({"page": index + 1, "status": "added", "text": _line_diff("", _page_text(second[index]))})
                changed_pages += 1
                continue
            if index >= second.page_count:
                pages.append({"page": index + 1, "status": "removed", "text": _line_diff(_page_text(first[index]), "")})
                changed_pages += 1
                continue
            old_page, new_page = first[index], second[index]
            old_text, new_text = _page_text(old_page), _page_text(new_page)
            diff = _line_diff(old_text, new_text)
            old_size = [round(old_page.rect.width, 2), round(old_page.rect.height, 2)]
            new_size = [round(new_page.rect.width, 2), round(new_page.rect.height, 2)]
            geometry_changed = old_size != new_size
            visual = _visual_diff(_render_page(old_page), _render_page(new_page))
            text_changed = diff["changed_blocks"] > 0
            visual_changed = visual["changed"] is True
            status = "changed" if text_changed or geometry_changed or visual_changed else "same"
            if status != "same":
                changed_pages += 1
            pages.append({
                "page": index + 1,
                "status": status,
                "geometry_changed": geometry_changed,
                "visual": visual,
                "original_size_pt": old_size,
                "revised_size_pt": new_size,
                "text": diff,
            })
        return {
            "original_page_count": first.page_count,
            "revised_page_count": second.page_count,
            "changed_pages": changed_pages,
            "same_pages": total - changed_pages,
            "pages": pages,
            "comparison_scope": ["extractable_text", "page_dimensions", "rendered_visual_pixels"],
            "limitations": [
                "المقارنة البصرية على صورة مصغرة للصفحة؛ قد لا تكشف الفروق الدقيقة جدًا.",
                "لا تحدد المقارنة البصرية وحدها نوع العنصر الذي تغيّر؛ راجع حدود الاختلاف المعروضة.",
                "ترتيب النص المستخرج قد يختلف عن ترتيب العرض في بعض ملفات PDF متعددة الأعمدة.",
            ],
        }
    finally:
        first.close()
        second.close()
