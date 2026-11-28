#!/usr/bin/env python3
"""Exercise both Word export paths on a real public Arabic legal PDF."""
from __future__ import annotations

import io
import json
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pymupdf
from docx import Document
from fastapi.testclient import TestClient

from document_export import create_docx
from pdf_to_docx import analyze_pdf_docx_quality, create_ocr_docx
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


def merge_native_same_baseline(lines: list[dict]) -> list[dict]:
    """Join PDF text fragments sharing one baseline without merging separate columns."""
    groups: list[dict] = []
    for line in sorted(lines, key=lambda item: (
        float((item.get("bbox") or [0, 0, 0, 0])[1]),
        float((item.get("bbox") or [0, 0, 0, 0])[0]),
    )):
        box = line.get("bbox") or [0, 0, 0, 0]
        x0, y0, x1, y1 = [float(value) for value in box]
        best = None
        for group in groups:
            if group["column"] != line.get("column", 1) or group["region"] != line.get("region"):
                continue
            overlap = max(0.0, min(y1, group["y1"]) - max(y0, group["y0"]))
            min_height = max(1.0, min(y1 - y0, group["y1"] - group["y0"]))
            center_gap = abs((y0 + y1) / 2 - group["center_y"])
            if overlap / min_height >= 0.55 or center_gap <= max(2.0, min_height * 0.22):
                best = group
                break
        if best is None:
            groups.append({
                "items": [line], "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "center_y": (y0 + y1) / 2,
                "column": line.get("column", 1), "region": line.get("region"),
            })
        else:
            best["items"].append(line)
            best["x0"] = min(best["x0"], x0)
            best["y0"] = min(best["y0"], y0)
            best["x1"] = max(best["x1"], x1)
            best["y1"] = max(best["y1"], y1)
            best["center_y"] = (best["y0"] + best["y1"]) / 2
    merged = []
    for group in groups:
        ordered = sorted(group["items"], key=lambda item: float((item.get("bbox") or [0, 0, 0, 0])[0]), reverse=True)
        text = " ".join(str(item.get("text", "")).strip() for item in ordered).strip()
        if not text:
            continue
        item = dict(ordered[0])
        item["text"] = text
        item["bbox"] = [round(group["x0"]), round(group["y0"]), round(group["x1"]), round(group["y1"])]
        item["reading_order"] = min(int(value.get("reading_order", 0) or 0) for value in ordered)
        merged.append(item)
    return sorted(merged, key=lambda item: int(item.get("reading_order", 0) or 0))


def render_docx_metrics(data: bytes, source_page: pymupdf.Page) -> dict:
    """Round-trip DOCX through LibreOffice and measure page count and physical size."""
    with tempfile.TemporaryDirectory(prefix="alfalqi-docx-render-") as temp:
        root = Path(temp)
        input_path = root / "candidate.docx"
        output_dir = root / "out"
        profile = root / "lo-profile"
        output_dir.mkdir()
        input_path.write_bytes(data)
        result = subprocess.run(
            ["libreoffice", f"-env:UserInstallation={profile.as_uri()}",
             "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(input_path)],
            capture_output=True, text=True, timeout=90, check=False,
        )
        pdf_path = output_dir / "candidate.pdf"
        if result.returncode != 0 or not pdf_path.is_file():
            return {"status": "render_failed", "returncode": result.returncode,
                    "stderr": (result.stderr or result.stdout)[-1200:]}
        rendered = pymupdf.open(pdf_path)
        try:
            first = rendered[0]
            width_error = abs(first.rect.width - source_page.rect.width) / source_page.rect.width * 100
            height_error = abs(first.rect.height - source_page.rect.height) / source_page.rect.height * 100
            return {
                "status": "rendered", "page_count": rendered.page_count,
                "first_page_width_pt": round(first.rect.width, 2),
                "first_page_height_pt": round(first.rect.height, 2),
                "source_page_width_pt": round(source_page.rect.width, 2),
                "source_page_height_pt": round(source_page.rect.height, 2),
                "width_error_percent": round(width_error, 2),
                "height_error_percent": round(height_error, 2),
                "rendered_text_chars": len(first.get_text("text") or ""),
            }
        finally:
            rendered.close()


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
with TestClient(main.app) as client:
    native_response = client.post(
        "/api/convert/pdf-to-docx",
        files={"file": ("real-dubai-law-page1.pdf", native_pdf, "application/pdf")},
    )
    if native_response.status_code != 200:
        raise SystemExit(f"Formatted PDF-to-Word API failed: {native_response.status_code} {native_response.text[:1000]}")
    native_docx = native_response.content
    native_engine = native_response.headers.get("X-Conversion-Engine", "unknown")
if not native_docx.startswith(b"PK"):
    raise SystemExit("Formatted PDF-to-Word conversion did not produce a DOCX package.")
native_text, native_paragraphs, native_images = read_docx(native_docx)
if len(normalize(native_text)) < 30:
    raise SystemExit("Formatted PDF-to-Word output contains too little editable text.")
native_quality = analyze_pdf_docx_quality(native_pdf, native_docx)
(OUT / "real-dubai-law-formatted.docx").write_bytes(native_docx)

# Experimental alternative: rebuild a native text PDF from line geometry rather than pdf2docx.
# This is diagnostic only; the production route is not switched unless the candidate wins.
native_layout_result = main._native_pdf_page_result(source[0], main.OCR_DPI / 72.0)
native_layout_candidate = None
native_merged_candidate = None
if native_layout_result and native_layout_result.get("lines"):
    merged_lines = merge_native_same_baseline(native_layout_result["lines"])
    merged_bytes = create_ocr_docx([{
        "page": 1,
        "dpi": main.OCR_DPI,
        "page_width_pt": float(source[0].rect.width),
        "page_height_pt": float(source[0].rect.height),
        "direction": (native_layout_result.get("layout") or {}).get("direction", "rtl"),
        "lines": merged_lines,
    }])
    merged_text, merged_paragraphs, merged_images = read_docx(merged_bytes)
    native_merged_candidate = {
        "status": "candidate_generated",
        "output_bytes": len(merged_bytes),
        "editable_chars": len(merged_text),
        "paragraphs": merged_paragraphs,
        "images": merged_images,
        "quality": analyze_pdf_docx_quality(native_pdf, merged_bytes),
        "cer_vs_pdf_text": cer(reference, merged_text),
        "render": render_docx_metrics(merged_bytes, source[0]),
    }
    (OUT / "real-dubai-law-native-merged-candidate.docx").write_bytes(merged_bytes)
    render_check = native_merged_candidate["render"]
    # Experimental candidate: report regressions without aborting the complete suite.
    native_merged_candidate["diagnostics"] = {
        "one_page_match": render_check.get("status") == "rendered" and render_check.get("page_count") == 1,
        "page_geometry_match": (
            render_check.get("status") == "rendered"
            and render_check.get("width_error_percent", 100) <= 0.5
            and render_check.get("height_error_percent", 100) <= 0.5
        ),
        "text_coverage_complete": native_merged_candidate["quality"].get("text_coverage_percent") == 100.0,
        "production_eligible": False,
    }
native_words_result = main._native_pdf_page_result_words(source[0], main.OCR_DPI / 72.0)
native_words_candidate = None
if native_words_result and native_words_result.get("lines"):
    native_words_bytes = create_ocr_docx([{
        "page": 1,
        "dpi": main.OCR_DPI,
        "page_width_pt": float(source[0].rect.width),
        "page_height_pt": float(source[0].rect.height),
        "direction": (native_words_result.get("layout") or {}).get("direction", "rtl"),
        "lines": native_words_result["lines"],
    }])
    native_words_text, native_words_paragraphs, native_words_images = read_docx(native_words_bytes)
    native_words_candidate = {
        "status": "candidate_generated",
        "output_bytes": len(native_words_bytes),
        "editable_chars": len(native_words_text),
        "paragraphs": native_words_paragraphs,
        "images": native_words_images,
        "quality": analyze_pdf_docx_quality(native_pdf, native_words_bytes),
        "cer_vs_pdf_text": cer(reference, native_words_text),
    }
    (OUT / "real-dubai-law-native-words-candidate.docx").write_bytes(native_words_bytes)
    (OUT / "real-dubai-law-native-words-lines.json").write_text(
        json.dumps({
            "layout": native_words_result.get("layout") or {},
            "lines": native_words_result.get("lines") or [],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
if native_layout_result:
    (OUT / "real-dubai-law-native-layout-lines.json").write_text(
        json.dumps({
            "layout": native_layout_result.get("layout") or {},
            "lines": native_layout_result.get("lines") or [],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
if native_layout_result and native_layout_result.get("lines"):
    native_layout_bytes = create_ocr_docx([{
        "page": 1,
        "dpi": main.OCR_DPI,
        "direction": (native_layout_result.get("layout") or {}).get("direction", "rtl"),
        "lines": native_layout_result["lines"],
    }])
    native_layout_text, native_layout_paragraphs, native_layout_images = read_docx(native_layout_bytes)
    native_layout_candidate = {
        "status": "candidate_generated",
        "output_bytes": len(native_layout_bytes),
        "editable_chars": len(native_layout_text),
        "paragraphs": native_layout_paragraphs,
        "images": native_layout_images,
        "quality": analyze_pdf_docx_quality(native_pdf, native_layout_bytes),
        "cer_vs_pdf_text": cer(reference, native_layout_text),
    }
    (OUT / "real-dubai-law-native-layout-candidate.docx").write_bytes(native_layout_bytes)

# Button 2: "تصدير Word" -> /api/export/docx, using extracted PDF text.
with TestClient(main.app) as client:
    export_response = client.post(
        "/api/export/docx",
        json={"pages": [{"page": 1, "text": reference}]},
    )
    if export_response.status_code != 200:
        raise SystemExit(f"Text-to-Word API failed: {export_response.status_code} {export_response.text[:1000]}")
    text_export = export_response.content
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
with TestClient(main.app) as client:
    scanned_response = client.post(
        "/api/convert/pdf-to-docx",
        files={"file": ("real-dubai-law-scanned.pdf", scanned_pdf, "application/pdf")},
    )
    if scanned_response.status_code != 200:
        raise SystemExit(f"Scanned PDF-to-Word API failed: {scanned_response.status_code} {scanned_response.text[:1000]}")
    scanned_docx = scanned_response.content
    scanned_engine = scanned_response.headers.get("X-Conversion-Engine", "unknown")
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
    "native_layout_candidate": native_layout_candidate,
    "native_merged_candidate": native_merged_candidate,
    "native_words_candidate": native_words_candidate,
    "formatted_pdf_to_docx": {
        "status": "passed",
        "engine": native_engine,
        "output_bytes": len(native_docx),
        "editable_chars": len(native_text),
        "paragraphs": native_paragraphs,
        "images": native_images,
        "quality": native_quality,
        "api_status": native_response.status_code,
        "cer_vs_pdf_text": cer(reference, native_text),
        "render": render_docx_metrics(native_docx, source[0]),
    },
    "text_export_to_docx": {
        "status": "passed",
        "api_status": export_response.status_code,
        "output_bytes": len(text_export),
        "editable_chars": len(export_text),
        "paragraphs": export_paragraphs,
        "rtl_arabic_present": any("\u0600" <= ch <= "\u06ff" for ch in export_text),
    },
    "scanned_pdf_ocr_to_docx": {
        "status": "passed",
        "engine": scanned_engine,
        "api_status": scanned_response.status_code,
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
