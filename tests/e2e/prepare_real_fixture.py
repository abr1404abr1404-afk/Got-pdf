#!/usr/bin/env python3
"""Download and rasterize a real, public Arabic legal PDF page for browser OCR tests."""
from pathlib import Path
import json
import requests
import pymupdf

URL = "https://dlp.dubai.gov.ae/Legislation%20Ar%20Reference/2025/%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%B1%D9%82%D9%85%20(7)%20%D9%84%D8%B3%D9%86%D8%A9%202025%20%D8%A8%D8%B4%D8%A3%D9%86%20%D8%AA%D9%86%D8%B8%D9%8A%D9%85%20%D9%85%D8%B2%D8%A7%D9%88%D9%84%D8%A9%20%D8%A3%D9%86%D8%B4%D8%B7%D8%A9%20%D8%A7%D9%84%D9%85%D9%82%D8%A7%D9%88%D9%84%D8%A7%D8%AA.pdf"
OUT = Path("tests/e2e/fixtures")
OUT.mkdir(parents=True, exist_ok=True)
response = requests.get(URL, timeout=(20, 180), headers={"User-Agent": "GotPDF-browser-ocr-test/1.0"})
response.raise_for_status()
pdf_path = OUT / "real-dubai-law.pdf"
pdf_path.write_bytes(response.content)
doc = pymupdf.open(pdf_path)
page = doc[0]
pix = page.get_pixmap(matrix=pymupdf.Matrix(2.5, 2.5), alpha=False)
image_path = OUT / "real-dubai-law-page1.png"
pix.save(image_path)
(OUT / "real-dubai-law-page1.txt").write_text(page.get_text("text"), encoding="utf-8")
metadata = {"source": URL, "page": 1, "pdf_bytes": len(response.content),
            "image_width": pix.width, "image_height": pix.height,
            "reference_chars": len(page.get_text("text"))}
(OUT / "fixture-metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
doc.close()
print(json.dumps(metadata, ensure_ascii=False))
