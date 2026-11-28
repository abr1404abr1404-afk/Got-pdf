#!/usr/bin/env python3
"""Compare available server OCR engines on identical Arabic image fixtures."""
from __future__ import annotations

import io
import json
import os
import re
import time
import unicodedata
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
import pymupdf

BASE = os.environ.get("BACKEND_URL", "https://got-pdf.onrender.com").rstrip("/")
OUT = Path("ocr-engine-benchmark.json")
SESSION = requests.Session()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFC", value or "")
    value = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", value)
    return re.sub(r"\s+", "", value)


def distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def metrics(reference: str, actual: str) -> dict:
    expected, observed = normalize(reference), normalize(actual)
    errors = distance(expected, observed) if expected else 0
    return {
        "reference_chars": len(expected),
        "recognized_chars": len(observed),
        "cer": round(errors / max(1, len(expected)), 4),
        "character_accuracy_percent": round(max(0, 1 - errors / max(1, len(expected))) * 100, 2),
        "contains_arabic": any("\u0600" <= ch <= "\u06ff" for ch in actual),
    }


def font_path(candidates: list[str]) -> str:
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError("Arabic test font not found: " + ", ".join(candidates))


ARABIC_FONT = font_path([
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
])
LATIN_FONT = font_path([
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
])


def render_fixture(text: str, size: int, mixed: bool = False, degraded: bool = False) -> bytes:
    canvas = Image.new("RGB", (2200, 520), "white")
    draw = ImageDraw.Draw(canvas)
    arabic = ImageFont.truetype(ARABIC_FONT, size)
    latin = ImageFont.truetype(LATIN_FONT, max(34, size // 2))
    if mixed:
        draw.text((90, 45), "ALFAQI PDF 2026 | OCR 12345", font=latin, fill="black")
        draw.text((2110, 210), text, font=arabic, fill="black", direction="rtl", language="ar", anchor="ra")
    else:
        draw.text((2110, 150), text, font=arabic, fill="black", direction="rtl", language="ar", anchor="ra")
    if degraded:
        canvas = ImageEnhance.Contrast(canvas).enhance(0.72)
        canvas = canvas.filter(ImageFilter.GaussianBlur(0.45))
        canvas = canvas.rotate(0.7, resample=Image.Resampling.BICUBIC, fillcolor="white")
    result = io.BytesIO()
    canvas.save(result, format="PNG")
    return result.getvalue()


def real_pdf_page_fixture() -> dict:
    """Rasterize page one of a public Arabic government PDF for identical engine tests."""
    url = (
        "https://dlp.dubai.gov.ae/Legislation%20Ar%20Reference/2025/"
        "%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%B1%D9%82%D9%85%20(7)%20"
        "%D9%84%D8%B3%D9%86%D8%A9%202025%20%D8%A8%D8%B4%D8%A3%D9%86%20"
        "%D8%AA%D9%86%D8%B8%D9%8A%D9%85%20%D9%85%D8%B2%D8%A7%D9%88%D9%84%D8%A9%20"
        "%D8%A3%D9%86%D8%B4%D8%B7%D8%A9%20%D8%A7%D9%84%D9%85%D9%82%D8%A7%D9%88%D9%84%D8%A7%D8%AA.pdf"
    )
    response = SESSION.get(url, timeout=(20, 180), headers={"User-Agent": "GotPDF-OCR-benchmark/1.0"})
    response.raise_for_status()
    document = pymupdf.open(stream=response.content, filetype="pdf")
    try:
        page = document[0]
        reference = page.get_text("text") or ""
        if len(normalize(reference)) < 100:
            raise RuntimeError("Public Arabic PDF page one has insufficient reference text")
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0), alpha=False)
        image_bytes = pixmap.tobytes("png")
        return {
            "id": "real_dubai_law_pdf_page1",
            "text": reference,
            "language": "ara+eng",
            "bytes": image_bytes,
            "source_url": url,
            "source_page": 1,
            "image_width": pixmap.width,
            "image_height": pixmap.height,
        }
    finally:
        document.close()


def post_ocr(image_bytes: bytes, language: str, engine: str) -> dict:
    response = SESSION.post(
        BASE + "/api/ocr/image",
        files={"file": (f"arabic-{engine}.png", image_bytes, "image/png")},
        data={"language": language, "engine": engine},
        timeout=240,
    )
    # The production API applies a shared request limit. Retry 429 responses
    # after the advertised cooldown instead of marking every remaining engine
    # as failed in a single burst. Keep the benchmark sequential and fair.
    for attempt in range(4):
        if response.status_code != 429:
            break
        if attempt == 3:
            break
        retry_after = response.headers.get("Retry-After", "65")
        try:
            delay = max(60, min(90, int(float(retry_after))))
        except ValueError:
            delay = 65
        print(f"Rate limited; waiting {delay}s before retry ({attempt + 1}/3)", flush=True)
        time.sleep(delay)
        response = SESSION.post(
            BASE + "/api/ocr/image",
            files={"file": (f"arabic-{engine}.png", image_bytes, "image/png")},
            data={"language": language, "engine": engine},
            timeout=240,
        )
    if not response.ok:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:240]}")
    return response.json()



def post_paddle_vl(image_bytes: bytes) -> dict:
    response = SESSION.post(
        BASE + "/api/document/parse",
        files={"file": ("arabic-document.png", image_bytes, "image/png")},
        data={"export_docx": "false"},
        timeout=300,
    )
    if not response.ok:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:240]}")
    return response.json()


def main() -> None:
    health_response = SESSION.get(BASE + "/api/health", timeout=40)
    health_response.raise_for_status()
    health = health_response.json()
    assert health.get("ok") is True and health.get("arabic_ocr_ready") is True

    fixtures = [
        {"id": "naskh_clean", "text": "اختبار التعرف الضوئي العربي", "language": "ara", "bytes": render_fixture("اختبار التعرف الضوئي العربي", 150)},
        {"id": "mixed_arabic_latin_digits", "text": "ALFAQI PDF 2026 OCR 12345 الفلقي PDF تحويل المستندات العربية بدقة ١٢٣٤٥", "language": "ara+eng", "bytes": render_fixture("الفلقي PDF تحويل المستندات العربية بدقة ١٢٣٤٥", 118, mixed=True)},
        {"id": "small_arabic", "text": "هذا اختبار لقراءة النص العربي الصغير بدقة", "language": "ara", "bytes": render_fixture("هذا اختبار لقراءة النص العربي الصغير بدقة", 76)},
        {"id": "degraded_arabic", "text": "المجلس العربي للوثائق والتحول الرقمي", "language": "ara", "bytes": render_fixture("المجلس العربي للوثائق والتحول الرقمي", 108, degraded=True)},
        real_pdf_page_fixture(),
    ]

    candidates = ["tesseract"]
    if health.get("paddleocr_enabled"):
        candidates.extend(["paddleocr", "hybrid"])
    if health.get("paddleocr_vl_available"):
        candidates.append("paddleocr_vl")
    report = {
        "source": "Live Got-pdf backend; identical generated and public-PDF raster fixtures per engine",
        "health": {
            "mode": health.get("mode"),
            "arabic_ocr_ready": health.get("arabic_ocr_ready"),
            "paddleocr_enabled": health.get("paddleocr_enabled"),
            "paddleocr_status": health.get("paddleocr_status"),
            "paddleocr_remote_configured": health.get("paddleocr_remote_configured"),
            "paddleocr_vl_status": health.get("paddleocr_vl_status"),
        },
        "candidate_engines": candidates,
        "real_pdf_fixture_source": next((f.get("source_url") for f in fixtures if f["id"] == "real_dubai_law_pdf_page1"), None),
        "results": [],
    }

    for fixture in fixtures:
        for engine in candidates:
            started = time.perf_counter()
            item = {"fixture": fixture["id"], "engine": engine}
            try:
                payload = post_ocr(fixture["bytes"], fixture["language"], engine)
                lines = payload.get("lines") or []
                text = "\n".join(str(line.get("text", "")) for line in lines)
                item.update({
                    "status": "passed" if (lines or text.strip()) else "empty",
                    "latency_seconds": round(time.perf_counter() - started, 3),
                    "line_count": len(lines),
                    "metrics": metrics(fixture["text"], text),
                    "recognized_text": text[:1200],
                    "reported_engine": payload.get("engine") or payload.get("used_engine"),
                })
            except Exception as exc:
                item.update({
                    "status": "unavailable_or_failed",
                    "latency_seconds": round(time.perf_counter() - started, 3),
                    "error": str(exc)[:500],
                })
            report["results"].append(item)

    # A candidate wins only if it returns results for every fixture; summarize
    # mean CER and latency separately so speed cannot hide accuracy regressions.
    summary = []
    for engine in candidates:
        rows = [r for r in report["results"] if r["engine"] == engine and r["status"] == "passed"]
        if rows:
            summary.append({
                "engine": engine,
                "fixtures_passed": len(rows),
                "fixture_count": len(fixtures),
                "complete": len(rows) == len(fixtures),
                "mean_cer": round(sum(r["metrics"]["cer"] for r in rows) / len(rows), 4),
                "mean_latency_seconds": round(sum(r["latency_seconds"] for r in rows) / len(rows), 3),
            })
    report["summary"] = sorted(summary, key=lambda row: (
        not row["complete"], row["mean_cer"], row["mean_latency_seconds"]
    ))
    report["selection_note"] = (
        "Do not switch production default from this small synthetic benchmark alone; "
        "confirm the ranking on the public scanned-PDF fixture and handwritten/decorative samples."
    )
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert any(row["engine"] == "tesseract" and row["complete"] for row in summary), (
        "Baseline Tesseract did not complete all benchmark fixtures"
    )


if __name__ == "__main__":
    main()
