#!/usr/bin/env python3
"""Diagnostic multi-layout PDF->DOCX matrix with LibreOffice raster comparison.

Synthetic fixtures complement the public Arabic fixture: they isolate text-only,
table, two-column, and image-containing layouts. Visual scores are diagnostics,
not a pass/fail fidelity claim.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# Running a script by path puts tests/e2e on sys.path, not the repository root.
# Resolve the project root explicitly so `import main` works in CI and locally.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pymupdf
from PIL import Image, ImageChops
from docx import Document
from fastapi.testclient import TestClient

import main

OUT = ROOT / "tests" / "e2e" / "artifacts"
OUT.mkdir(parents=True, exist_ok=True)


def make_fixture(kind: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    if kind == "text-only":
        page.insert_text((72, 90), "Project Summary 2026", fontsize=18)
        page.insert_textbox((72, 125, 530, 310),
                            "This is a simple single-column document with paragraphs, "
                            "dates 27 November 2026, and identifiers ABC-123.",
                            fontsize=11, lineheight=1.5)
    elif kind == "table":
        page.insert_text((72, 70), "Quarterly Results", fontsize=18)
        x0, y0, x1, y1 = 72, 110, 540, 290
        rows, cols = 4, 3
        for r in range(rows + 1):
            y = y0 + (y1-y0)*r/rows
            page.draw_line((x0, y), (x1, y), color=(0, 0, 0), width=0.8)
        for c in range(cols + 1):
            x = x0 + (x1-x0)*c/cols
            page.draw_line((x, y0), (x, y1), color=(0, 0, 0), width=0.8)
        values = [["Region", "Orders", "Total"], ["North", "125", "9,250"],
                  ["Central", "98", "7,840"], ["South", "76", "5,320"]]
        for r, row in enumerate(values):
            for c, value in enumerate(row):
                page.insert_text((x0+12+c*(x1-x0)/cols, y0+30+r*(y1-y0)/rows),
                                 value, fontsize=10)
    elif kind == "two-column":
        page.insert_text((72, 80), "Two Column Layout", fontsize=18)
        page.insert_textbox((72, 115, 290, 650),
                            "LEFT COLUMN\n\n" + ("Left column paragraph with repeated content. " * 14),
                            fontsize=10, lineheight=1.35)
        page.insert_textbox((322, 115, 540, 650),
                            "RIGHT COLUMN\n\n" + ("Right column paragraph with distinct content. " * 14),
                            fontsize=10, lineheight=1.35)
    elif kind in {"image", "ocr-mixed"}:
        page.insert_text((72, 80), "Image and Caption" if kind == "image" else "OCR mixed layout", fontsize=18)
        image = Image.new("RGB", (160, 90), "white")
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image)
        draw.rectangle((6, 6, 154, 84), outline="black", width=3)
        draw.line((10, 75, 50, 20, 90, 60, 145, 15), fill="black", width=4)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        if kind == "image":
            page.insert_image(pymupdf.Rect(100, 130, 500, 330), stream=buf.getvalue())
            page.insert_text((100, 355), "Figure 1. Deterministic test graphic.", fontsize=10)
        else:
            page.insert_image(pymupdf.Rect(400, 360, 520, 440), stream=buf.getvalue())
            x0, y0, x1, y1 = 72, 140, 540, 300
            for rr in range(3):
                y = y0 + (y1-y0)*rr/2
                page.draw_line((x0, y), (x1, y), color=(0, 0, 0), width=0.8)
            for cc in range(3):
                x = x0 + (x1-x0)*cc/2
                page.draw_line((x, y0), (x, y1), color=(0, 0, 0), width=0.8)
            page.insert_text((95, 185), "Name", fontsize=10)
            page.insert_text((330, 185), "Value", fontsize=10)
            page.insert_text((95, 265), "Total", fontsize=10)
            page.insert_text((330, 265), "125", fontsize=10)
            page.insert_text((72, 500), "Figure 1. OCR layout image.", fontsize=10)
    else:
        raise ValueError(kind)
    data = doc.tobytes()
    doc.close()
    return data


def render_docx(data: bytes, root: Path) -> Path:
    source = root / "matrix.docx"
    output = root / "out"
    profile = root / "profile"
    output.mkdir()
    source.write_bytes(data)
    proc = subprocess.run(
        ["libreoffice", f"-env:UserInstallation={profile.as_uri()}",
         "--headless", "--convert-to", "pdf", "--outdir", str(output), str(source)],
        capture_output=True, text=True, timeout=90, check=False,
    )
    result = output / "matrix.pdf"
    if proc.returncode or not result.exists():
        raise RuntimeError(f"LibreOffice render failed: {proc.stderr[-1000:]}")
    return result


def visual_metrics(source_pdf: bytes, output_docx: bytes) -> dict:
    with tempfile.TemporaryDirectory(prefix="pdf-docx-matrix-") as temp:
        root = Path(temp)
        rendered_path = render_docx(output_docx, root)
        original = pymupdf.open(stream=source_pdf, filetype="pdf")
        rendered = pymupdf.open(rendered_path)
        try:
            if original.page_count != 1 or rendered.page_count != 1:
                return {"status": "not_comparable", "source_pages": original.page_count,
                        "output_pages": rendered.page_count}
            scale = 1.25
            a = Image.open(io.BytesIO(original[0].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png"))).convert("L")
            b = Image.open(io.BytesIO(rendered[0].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png"))).convert("L")
            source_size, output_size = a.size, b.size
            if b.size != a.size:
                b = b.resize(a.size, Image.Resampling.LANCZOS)
            aa = np.asarray(a, dtype=np.float32)
            bb = np.asarray(b, dtype=np.float32)
            mae = float(np.mean(np.abs(aa - bb)) / 255.0)
            agreement = float(np.mean(np.abs(aa - bb) <= 24))
            return {
                "status": "compared",
                "source_pixels": list(source_size),
                "output_pixels_before_alignment": list(output_size),
                "normalized_mean_absolute_error": round(mae, 5),
                "pixel_agreement_within_24_levels": round(agreement * 100, 2),
                "note": "Output raster resized to source dimensions for pixel diagnostics; not a strict SSIM score."
            }
        finally:
            original.close()
            rendered.close()


def run():
    reports = []
    # This is an isolated local integration test, not a public API load test.
    # Disable only the in-process request guard in this test process so the four
    # fixtures (plus the preceding real-PDF checks) cannot trip production quotas.
    main._guard_expensive_request = lambda *args, **kwargs: None
    for kind in ("text-only", "table", "two-column", "image", "ocr-mixed"):
        pdf = make_fixture(kind)
        with TestClient(main.app, client=(f"layout-matrix-{kind}", 50000)) as client:
            if kind == "ocr-mixed":
                from unittest.mock import patch
                fake_ocr = {
                    "engine": "tesseract", "image_width": 2040, "image_height": 2640,
                    "lines": [
                        {"text": "OCR mixed layout", "bbox": [240, 200, 1500, 320], "confidence": 99},
                        {"text": "Name", "bbox": [300, 500, 520, 570], "confidence": 99},
                        {"text": "Value", "bbox": [1050, 500, 1300, 570], "confidence": 99},
                        {"text": "Total", "bbox": [300, 850, 520, 920], "confidence": 99},
                        {"text": "125", "bbox": [1050, 850, 1300, 920], "confidence": 99},
                        {"text": "Figure 1. OCR layout image.", "bbox": [240, 1570, 1500, 1640], "confidence": 99},
                    ],
                    "layout": {"direction": "ltr", "column_count": 1},
                }
                fake_table = [{
                    "bbox": [220, 450, 1800, 1050], "direction": "ltr",
                    "rows": [["Name", "Value"], ["Total", "125"]],
                }]
                with patch.object(main, "_native_pdf_page_result", return_value=None), \
                     patch.object(main, "_hybrid", return_value=fake_ocr), \\
                     patch.object(main, "_detect_tables", return_value=fake_table):
                    response = client.post(
                        "/api/convert/pdf-to-docx",
                        files={"file": (f"{kind}.pdf", pdf, "application/pdf")},
                    )
            else:
                response = client.post(
                    "/api/convert/pdf-to-docx",
                    files={"file": (f"{kind}.pdf", pdf, "application/pdf")},
                )
            if response.status_code != 200 or not response.content.startswith(b"PK"):
                raise RuntimeError(f"{kind}: conversion failed ({response.status_code}) {response.text[:500]}")
            document = Document(io.BytesIO(response.content))
            report = {
                "fixture": kind,
                "status": "converted",
                "engine": response.headers.get("X-Conversion-Engine", "unknown"),
                "paragraphs": len([p for p in document.paragraphs if p.text.strip()]),
                "tables": len(document.tables),
                "inline_images": len(document.inline_shapes),
                "editable_text_chars": sum(len(p.text) for p in document.paragraphs)
                    + sum(len(cell.text) for table in document.tables for row in table.rows for cell in row.cells),
                "visual": visual_metrics(pdf, response.content),
            }
            reports.append(report)
            (OUT / f"layout-matrix-{kind}.docx").write_bytes(response.content)
    result = {"fixture_type": "synthetic diagnostic matrix", "cases": reports}
    (OUT / "pdf-to-docx-layout-matrix.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
