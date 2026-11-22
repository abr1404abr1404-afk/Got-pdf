from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import threading
from typing import Any

import cv2
import numpy as np
import pytesseract
import fitz
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps
from starlette.concurrency import run_in_threadpool

APP_NAME = "Alfalqi PDF OCR API"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "12"))
OCR_DPI = int(os.getenv("OCR_DPI", "240"))
OCR_MODE = os.getenv("OCR_MODE", "hybrid").lower()

app = FastAPI(title=APP_NAME, version="0.1.0", description="Hybrid Arabic/English OCR service for Alfalqi PDF")

origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_paddle_lock = threading.Lock()
_paddle_instances: dict[str, Any] = {}


def _check_size(data: bytes) -> None:
    if not data:
        raise HTTPException(400, "الملف فارغ")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"حجم الملف يتجاوز الحد ({MAX_UPLOAD_MB} MB)")


def _decode_image(data: bytes) -> np.ndarray:
    try:
        pil = Image.open(io.BytesIO(data))
        pil = ImageOps.exif_transpose(pil).convert("RGB")
        arr = np.array(pil)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception as exc:
        raise HTTPException(415, "تعذّر قراءة الصورة. جرّب PNG أو JPG.") from exc


def _preprocess(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    # Upscale small scans while limiting memory use.
    scale = min(2.0, max(1.0, 1800.0 / max(h, w)))
    if scale > 1.01:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Mild contrast normalization; avoid aggressive binarization that destroys Arabic dots.
    clahe = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    denoised = cv2.fastNlMeansDenoising(gray, None, 7, 7, 21)
    return cv2.cvtColor(denoised, cv2.COLOR_GRAY2BGR)


def _lang_pair(language: str) -> tuple[str, str]:
    value = (language or "ara+eng").lower()
    if value in {"ara", "ar", "arabic"}:
        return "ara", "ar"
    if value in {"eng", "en", "english"}:
        return "eng", "en"
    return "ara+eng", "ar"


def _tesseract(image: np.ndarray, language: str) -> tuple[list[dict], str | None]:
    tess_lang, _ = _lang_pair(language)
    try:
        # PSM 11 is useful for mixed page layouts; PSM 6 is retained as a second pass.
        outputs: list[dict] = []
        data = pytesseract.image_to_data(
            image,
            lang=tess_lang,
            config="--oem 1 --psm 11 -c preserve_interword_spaces=1",
            output_type=pytesseract.Output.DICT,
        )
        groups: dict[tuple, list[int]] = {}
        for i, raw_text in enumerate(data.get("text", [])):
            text = re.sub(r"\s+", " ", (raw_text or "")).strip()
            if not text:
                continue
            key = tuple(data[k][i] for k in ("page_num", "block_num", "par_num", "line_num"))
            groups.setdefault(key, []).append(i)
        for indices in groups.values():
            words = []
            for i in indices:
                word = re.sub(r"\s+", " ", (data["text"][i] or "")).strip()
                try: conf = float(data["conf"][i])
                except (ValueError, TypeError, KeyError): conf = 0.0
                if word and conf >= 10:
                    x, y = int(data["left"][i]), int(data["top"][i])
                    w, h = int(data["width"][i]), int(data["height"][i])
                    words.append((x, y, w, h, conf, word))
            if not words: continue
            # Arabic runs are read right-to-left; Latin runs left-to-right.
            rtl = any("\u0600" <= ch <= "\u06ff" for item in words for ch in item[5])
            words.sort(key=lambda z: z[0], reverse=rtl)
            x0 = min(z[0] for z in words); y0 = min(z[1] for z in words)
            x1 = max(z[0] + z[2] for z in words); y1 = max(z[1] + z[3] for z in words)
            text = " ".join(z[5] for z in words)
            conf = sum(z[4] for z in words) / len(words)
            outputs.append({"text": text, "confidence": conf, "bbox": [x0, y0, x1, y1], "engine": "tesseract"})
        return _dedupe(outputs), None
    except Exception as exc:
        return [], str(exc)


def _get_paddle(language: str):
    _, paddle_lang = _lang_pair(language)
    with _paddle_lock:
        if paddle_lang in _paddle_instances:
            return _paddle_instances[paddle_lang]
        from paddleocr import PaddleOCR
        # PaddleOCR 3.x supports Arabic through lang="ar".
        try:
            engine = PaddleOCR(lang=paddle_lang, device="cpu", use_doc_orientation_classify=False,
                               use_doc_unwarping=False, use_textline_orientation=True, show_log=False)
        except TypeError:
            # Compatibility path for PaddleOCR 2.x.
            engine = PaddleOCR(lang=paddle_lang, use_angle_cls=True, show_log=False, use_gpu=False)
        _paddle_instances[paddle_lang] = engine
        return engine


def _paddle(image: np.ndarray, language: str) -> tuple[list[dict], str | None]:
    try:
        engine = _get_paddle(language)
        rows: list[dict] = []
        # PaddleOCR 3.x result object / dict interface.
        if hasattr(engine, "predict"):
            result = engine.predict(image)
            for item in result or []:
                payload = item.json if hasattr(item, "json") else item
                if callable(payload):
                    payload = payload()
                if isinstance(payload, str):
                    try: payload = json.loads(payload)
                    except Exception: payload = {}
                if isinstance(payload, dict) and "res" in payload:
                    payload = payload["res"]
                if not isinstance(payload, dict):
                    continue
                texts = payload.get("rec_texts") or []
                scores = payload.get("rec_scores") or []
                boxes = payload.get("rec_polys") or payload.get("dt_polys") or []
                for text, score, box in zip(texts, scores, boxes):
                    pts = np.asarray(box, dtype=float).reshape(-1, 2)
                    if len(pts) < 4:
                        continue
                    x0, y0 = pts.min(axis=0); x1, y1 = pts.max(axis=0)
                    rows.append({"text": str(text).strip(), "confidence": float(score) * 100,
                                 "bbox": [int(x0), int(y0), int(x1), int(y1)], "engine": "paddleocr"})
        else:
            # PaddleOCR 2.x returns [page][line][box, (text, score)].
            result = engine.ocr(image, cls=True)
            for page in result or []:
                for line in page or []:
                    box, pair = line[0], line[1]
                    pts = np.asarray(box, dtype=float).reshape(-1, 2)
                    x0, y0 = pts.min(axis=0); x1, y1 = pts.max(axis=0)
                    rows.append({"text": str(pair[0]).strip(), "confidence": float(pair[1]) * 100,
                                 "bbox": [int(x0), int(y0), int(x1), int(y1)], "engine": "paddleocr"})
        return [r for r in rows if r["text"]], None
    except Exception as exc:
        return [], str(exc)


def _iou(a: list[int], b: list[int]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    aa = max(1, (a[2] - a[0]) * (a[3] - a[1]))
    bb = max(1, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / max(1, min(aa, bb))


def _dedupe(rows: list[dict]) -> list[dict]:
    rows = sorted(rows, key=lambda r: r["confidence"], reverse=True)
    kept: list[dict] = []
    for row in rows:
        if not any(_iou(row["bbox"], other["bbox"]) > 0.55 for other in kept):
            kept.append(row)
    return kept


def _reading_order(rows: list[dict]) -> list[dict]:
    """Order OCR line boxes top-to-bottom and each line by its writing direction."""
    if len(rows) < 2:
        return rows
    ordered = sorted(rows, key=lambda r: (r["bbox"][1] + r["bbox"][3]) / 2)
    heights = sorted(max(1, r["bbox"][3] - r["bbox"][1]) for r in ordered)
    tolerance = max(8.0, heights[len(heights) // 2] * 0.65)
    bands: list[list[dict]] = []
    centers: list[float] = []
    for row in ordered:
        center = (row["bbox"][1] + row["bbox"][3]) / 2
        if not bands or abs(center - centers[-1]) > tolerance:
            bands.append([row])
            centers.append(center)
        else:
            bands[-1].append(row)
            centers[-1] = sum((item["bbox"][1] + item["bbox"][3]) / 2 for item in bands[-1]) / len(bands[-1])

    result: list[dict] = []
    for band in bands:
        text = " ".join(item.get("text", "") for item in band)
        arabic_chars = sum("\u0600" <= ch <= "\u06ff" for ch in text)
        latin_chars = sum(("a" <= ch.lower() <= "z") for ch in text)
        rtl = arabic_chars >= latin_chars
        result.extend(sorted(band, key=lambda r: r["bbox"][0], reverse=rtl))
    return result


def _hybrid(image: np.ndarray, language: str) -> dict:
    prepared = _preprocess(image)
    paddle_rows, paddle_error = _paddle(prepared, language)
    tess_rows, tess_error = _tesseract(prepared, language)
    if paddle_rows and tess_rows:
        merged = _dedupe(paddle_rows + tess_rows)
        used = "hybrid"
    elif paddle_rows:
        merged, used = paddle_rows, "paddleocr"
    elif tess_rows:
        merged, used = tess_rows, "tesseract"
    else:
        merged, used = [], "none"
    h, w = prepared.shape[:2]
    merged = _reading_order(merged)
    return {
        "engine": used,
        "image_width": w,
        "image_height": h,
        "lines": merged,
        "engines": {"paddleocr": {"available": paddle_error is None, "error": paddle_error},
                    "tesseract": {"available": tess_error is None, "error": tess_error}},
    }


@app.get("/api/health")
def health():
    return {"ok": True, "service": APP_NAME, "mode": OCR_MODE, "max_upload_mb": MAX_UPLOAD_MB,
            "max_pdf_pages": MAX_PDF_PAGES}


@app.post("/api/ocr/image")
async def ocr_image(file: UploadFile = File(...), language: str = Form("ara+eng")):
    data = await file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    _check_size(data)
    image = _decode_image(data)
    result = await run_in_threadpool(_hybrid, image, language)
    if not result["lines"]:
        errors = result["engines"]
        raise HTTPException(503, {"message": "لم يتمكن أي محرك من استخراج نص. تحقق من تثبيت نماذج العربية والإنجليزية.", "engines": errors})
    return result


@app.post("/api/ocr/pdf")
async def ocr_pdf(file: UploadFile = File(...), language: str = Form("ara+eng"), dpi: int = Form(OCR_DPI)):
    data = await file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    _check_size(data)
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise HTTPException(415, "الملف ليس PDF صالحًا أو أنه محمي بكلمة مرور") from exc
    if doc.page_count > MAX_PDF_PAGES:
        raise HTTPException(413, f"عدد الصفحات يتجاوز الحد ({MAX_PDF_PAGES})")
    scale = max(1.0, min(4.0, dpi / 72.0))
    pages = []
    for index, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
        else:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        result = await run_in_threadpool(_hybrid, image, language)
        pages.append({"page": index + 1, "width_points": page.rect.width, "height_points": page.rect.height,
                      "ocr": result})
    doc.close()
    return {"pages": pages, "page_count": len(pages)}
