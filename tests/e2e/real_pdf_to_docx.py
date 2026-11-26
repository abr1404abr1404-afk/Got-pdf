#!/usr/bin/env python3
"""Exercise both Word export paths on a real public Arabic legal PDF."""
from __future__ import annotations

import io
import json
import re
import unicodedata
from pathlib import Path

import pymupdf
from docx import Document

from document_export import create_docx
from pdf_to_docx import analyze_pdf_docx_quality
import main

ROOT = Path("tests/e2e")
FIXTURE = ROOT / "fixtures" / "real-dubai-law.pdf"
OUT = ROOT / "artifacts"
OUT.mkdir(parents=True, exist_ok=True)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFC", value or "")
    value = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", value)
    return re.sub(r"\s+", "", value)


def cer(reference: str, actual: str) -> float | None:
    a, b = normalize(reference), normalize(actual)
    if not a:
        return None
    prev = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        cur = [i]
        for j, char_b in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (char_a != char_b)))
        prev = cur
    return round(prev[-1] / len(a), 4)


def read_docx(data: bytes) -> tuple[str, int, int]:
    document = Document(io.BytesIO(data))
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    text = "\n".join(paragraphs)
    return text, len(paragraphs), len(document.inline_shapes)


if not FIXTURE.is_file():
    raise SystemExit(f"Real PDF fixture not found: {FIXTURE}")

source = pymupdf.open(FIXTURE)
if source.page_count < 1:
    raise SystemExit("Real PDF has no pages.")
reference = source[0].get_text("text") or ""
if len(normalize(reference)) < 100:
    raise SystemExit("Real PDF page 1 has insufficient selectable reference text.")

# Limit the live test to one authentic page while preserving its original structure.
one_page = pymupdf.open()
one_page.insert_pdf(source, from_page=0, to_page=0)
native_pdf = one_page.tobytes()
one_page.close()

# Button 1: "تحويل PDF إلى Word بالتنسيق" -> /api/convert/pdf-to-docx
native_docx, native_engine = main._convert_pdf_to_docx_adaptive(native_pdf)
if not native_docx.startswith(b"PK"):
    raise SystemExit("Formatted PDF-to-Word conversion did not produce a DOCX package.")
native_text, native_paragraphs, native_images = read_docx(native_docx)
if len(normalize(native_text)) < 30:
    raise SystemExit("Formatted PDF-to-Word output contains too little editable text.")
native_quality = analyze_pdf_docx_quality(native_pdf, native_docx)
(OUT / "real-dubai-law-formatted.docx").write_bytes(native_docx)

# Button 2: "تصدير Word" -> /api/export/docx, using extracted PDF text.
text_export = create_docx([{"page": 1, "text": reference}])
export_text, export_paragraphs, export_images = read_docx(text_export)
if len(normalize(export_text)) < 30:
    raise SystemExit("Text-to-Word export did not produce editable text.")
(OUT / "real-dubai-law-text-export.docx").write_bytes(text_export)

# Also exercise the formatted converter's scanned-PDF fallback with a real raster page.
page = source[0]
pix = page.get_pixmap(matrix=pymupdf.Matrix(2.5, 2.5), alpha=False)
scanned = pymupdf.open()
scan_page = scanned.new_page(width=page.rect.width, height=page.rect.height)
scan_page.insert_image(scan_page.rect, stream=pix.tobytes("png"))
scanned_pdf = scanned.tobytes()
scanned.close()
scanned_docx, scanned_engine = main._convert_pdf_to_docx_adaptive(scanned_pdf)
if not scanned_docx.startswith(b"PK"):
    raise SystemExit("Scanned-PDF OCR conversion did not produce a DOCX package.")
scanned_text, scanned_paragraphs, scanned_images = read_docx(scanned_docx)
if len(normalize(scanned_text)) < 10:
    raise SystemExit("Scanned-PDF OCR-to-Word output contains too little editable text.")
(OUT / "real-dubai-law-scanned-ocr.docx").write_bytes(scanned_docx)

report = {
    "source": "Dubai government public legal PDF, first page",
    "source_url": "https://dlp.dubai.gov.ae/",
    "source_page_count": source.page_count,
    "tested_pages": 1,
    "source_reference_chars": len(reference),
    "formatted_pdf_to_docx": {
        "status": "passed",
        "engine": native_engine,
        "output_bytes": len(native_docx),
        "editable_chars": len(native_text),
        "paragraphs": native_paragraphs,
        "images": native_images,
        "quality": native_quality,
        "cer_vs_pdf_text": cer(reference, native_text),
    },
    "text_export_to_docx": {
        "status": "passed",
        "output_bytes": len(text_export),
        "editable_chars": len(export_text),
        "paragraphs": export_paragraphs,
        "rtl_arabic_present": any("\u0600" <= ch <= "\u06ff" for ch in export_text),
    },
    "scanned_pdf_ocr_to_docx": {
        "status": "passed",
        "engine": scanned_engine,
        "output_bytes": len(scanned_docx),
        "editable_chars": len(scanned_text),
        "arabic_chars": sum("\u0600" <= ch <= "\u06ff" for ch in scanned_text),
        "paragraphs": scanned_paragraphs,
        "cer_vs_pdf_text_reference": cer(reference, scanned_text),
    },
}
source.close()
(OUT / "real-pdf-to-docx-results.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(report, ensure_ascii=False, indent=2))
