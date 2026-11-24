"""Create OCR text layers in existing PDFs without rasterizing the source pages."""
from __future__ import annotations

import glob
import json
import re
import unicodedata
from typing import Any

import pymupdf

ARABIC_RE = re.compile(r"[\\u0600-\\u06FF\\u0750-\\u077F\\u08A0-\\u08FF]")
ARABIC_RUNS_RE = re.compile(r"([\\u0600-\\u06FF\\u0750-\\u077F\\u08A0-\\u08FF]+|[^\\u0600-\\u06FF\\u0750-\\u077F\\u08A0-\\u08FF]+)")
MAX_OCR_PAGES = 200
MAX_OCR_LINES = 20000
MAX_LINE_LENGTH = 1000


def _arabic_font_path() -> str | None:
    candidates = (
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    )
    for candidate in candidates:
        if __import__("os").path.isfile(candidate):
            return candidate
    matches = glob.glob("/usr/share/fonts/**/*Arabic*Regular.ttf", recursive=True)
    return matches[0] if matches else None


def _reverse_graphemes(value: str) -> str:
    """Reverse Arabic grapheme-like clusters while keeping combining marks attached."""
    clusters: list[str] = []
    for char in value:
        if unicodedata.combining(char) and clusters:
            clusters[-1] += char
        else:
            clusters.append(char)
    return "".join(reversed(clusters))


def _validated_pages(raw: str | dict[str, Any], page_count: int) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("بيانات OCR غير صالحة.") from exc
    entries = payload.get("pages") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or len(entries) > min(page_count, MAX_OCR_PAGES):
        raise ValueError("قائمة صفحات OCR غير صالحة أو تتجاوز الحد.")
    cleaned: list[dict[str, Any]] = []
    total_lines = 0
    seen: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("بيانات إحدى صفحات OCR غير صالحة.")
        try:
            page_number = int(entry.get("page"))
        except (TypeError, ValueError) as exc:
            raise ValueError("رقم صفحة OCR غير صالح.") from exc
        if page_number < 1 or page_number > page_count or page_number in seen:
            raise ValueError("رقم صفحة OCR خارج نطاق الملف أو مكرر.")
        seen.add(page_number)
        lines = entry.get("lines")
        if not isinstance(lines, list):
            raise ValueError("قائمة أسطر OCR غير صالحة.")
        total_lines += len(lines)
        if total_lines > MAX_OCR_LINES:
            raise ValueError("عدد أسطر OCR يتجاوز الحد الآمن.")
        safe_lines = []
        for line in lines:
            if not isinstance(line, dict):
                continue
            text = str(line.get("text") or "").strip()
            box = line.get("bbox")
            if not text or len(text) > MAX_LINE_LENGTH or not isinstance(box, (list, tuple)) or len(box) != 4:
                continue
            try:
                x0, y0, x1, y1 = (float(value) for value in box)
            except (TypeError, ValueError):
                continue
            if not all(map(__import__("math").isfinite, (x0, y0, x1, y1))) or x1 <= x0 or y1 <= y0:
                continue
            safe_lines.append({"text": text, "bbox": (x0, y0, x1, y1)})
        cleaned.append({"page": page_number, "lines": safe_lines})
    if not any(item["lines"] for item in cleaned):
        raise ValueError("لا توجد أسطر OCR صالحة لإضافتها إلى PDF.")
    return cleaned


def add_searchable_text_layer(pdf_bytes: bytes, ocr_data: str | dict[str, Any]) -> bytes:
    """Embed invisible, selectable OCR text at supplied PDF-point bounding boxes."""
    if not pdf_bytes:
        raise ValueError("ملف PDF فارغ.")
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError("الملف ليس PDF صالحًا.") from exc
    try:
        if document.needs_pass:
            raise ValueError("ملف PDF محمي بكلمة مرور.")
        if document.page_count < 1 or document.page_count > 500:
            raise ValueError("عدد صفحات PDF غير صالح أو يتجاوز 500 صفحة.")
        entries = _validated_pages(ocr_data, document.page_count)
        has_arabic = any(ARABIC_RE.search(line["text"]) for item in entries for line in item["lines"])
        arabic_font = _arabic_font_path() if has_arabic else None
        if has_arabic and not arabic_font:
            raise ValueError("خط العربية غير متوفر على الخادم. ثبّت fonts-noto-core ثم أعد النشر.")
        for item in entries:
            page = document.load_page(item["page"] - 1)
            bounds = page.mediabox
            for line in item["lines"]:
                x0, y0, x1, y1 = line["bbox"]
                # OCR coordinates are PDF points in the unrotated page coordinate space.
                x0 = max(float(bounds.x0), min(float(bounds.x1), x0))
                x1 = max(float(bounds.x0), min(float(bounds.x1), x1))
                y0 = max(float(bounds.y0), min(float(bounds.y1), y0))
                y1 = max(float(bounds.y0), min(float(bounds.y1), y1))
                if x1 - x0 < 1 or y1 - y0 < 1:
                    continue
                height = y1 - y0
                fontsize = max(4.0, min(30.0, height * 0.62))
                baseline = max(y0 + fontsize, min(y1, y1 - max(0.5, height * 0.08)))
                runs = ARABIC_RUNS_RE.findall(line["text"])
                for run in runs:
                    if not run:
                        continue
                    if ARABIC_RE.search(run):
                        page.insert_text(
                            (x0, baseline), _reverse_graphemes(run),
                            fontfile=arabic_font, fontname="alfalqi_arabic",
                            fontsize=fontsize, render_mode=3, overlay=True,
                        )
                    else:
                        page.insert_text(
                            (x0, baseline), run, fontname="helv",
                            fontsize=fontsize, render_mode=3, overlay=True,
                        )
        return document.tobytes(garbage=4, deflate=True, use_objstms=1)
    finally:
        document.close()
