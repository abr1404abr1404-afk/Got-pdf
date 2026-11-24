"""Page-by-page PDF comparison with bounded text extraction and safe summaries."""
from __future__ import annotations

import difflib
from typing import Any

import pymupdf

MAX_COMPARE_PAGES = 30
MAX_TEXT_CHARS_PER_PAGE = 100_000
MAX_DIFF_LINES = 80


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
    old_lines = before.splitlines()
    new_lines = after.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
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
        "truncated": len(added) > MAX_DIFF_LINES or len(removed) > MAX_DIFF_LINES,
    }


def compare_pdf_bytes(original: bytes, revised: bytes) -> dict[str, Any]:
    """Compare extracted text and page geometry; never modifies either source."""
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
            text_changed = diff["changed_blocks"] > 0
            status = "changed" if text_changed or geometry_changed else "same"
            if status != "same":
                changed_pages += 1
            pages.append({
                "page": index + 1,
                "status": status,
                "geometry_changed": geometry_changed,
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
            "comparison_scope": ["extractable_text", "page_dimensions"],
            "limitations": [
                "لا تكشف هذه المرحلة التغييرات البصرية داخل الصور أو الرسومات أو النصوص الممسوحة ضوئيًا غير القابلة للاستخراج.",
                "ترتيب النص المستخرج قد يختلف عن ترتيب العرض في بعض ملفات PDF متعددة الأعمدة.",
            ],
        }
    finally:
        first.close()
        second.close()
