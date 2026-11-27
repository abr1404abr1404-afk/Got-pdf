from __future__ import annotations

import asyncio
import io
import os
import threading
from typing import Any

import numpy as np
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from PIL import Image, ImageOps
from starlette.concurrency import run_in_threadpool

APP_KEY = os.getenv("PADDLE_WORKER_API_KEY", "").strip()
MAX_UPLOAD_MB = min(20, max(1, int(os.getenv("MAX_UPLOAD_MB", "12"))))
MAX_PIXELS = min(20_000_000, max(1_000_000, int(os.getenv("MAX_IMAGE_PIXELS", "12000000"))))
CPU_THREADS = min(4, max(1, int(os.getenv("PADDLE_CPU_THREADS", "2"))))
app = FastAPI(title="Got-pdf remote PaddleOCR worker", version="1.0.0")
_model = None
_model_lock = threading.Lock()
_inference_lock = asyncio.Semaphore(1)


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from paddleocr import PaddleOCR
                _model = PaddleOCR(
                    ocr_version="PP-OCRv5",
                    lang="ar",
                    device="cpu",
                    cpu_threads=CPU_THREADS,
                    enable_mkldnn=False,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
    return _model


def _rows_from_result(result: Any) -> list[dict]:
    rows: list[dict] = []
    for item in result or []:
        payload = getattr(item, "json", item)
        if callable(payload):
            payload = payload()
        if isinstance(payload, str):
            import json
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        if not isinstance(payload, dict):
            continue
        if isinstance(payload.get("res"), dict):
            payload = payload["res"]
        texts = payload.get("rec_texts") or []
        scores = payload.get("rec_scores") or []
        boxes = payload.get("rec_boxes") or payload.get("rec_polys") or payload.get("dt_polys") or []
        for index, value in enumerate(texts):
            text = str(value or "").strip()
            if not text or index >= len(boxes):
                continue
            try:
                coords = np.asarray(boxes[index], dtype=float)
                if coords.ndim == 2 and coords.shape[0] >= 4:
                    x0, y0 = coords.min(axis=0)[:2]
                    x1, y1 = coords.max(axis=0)[:2]
                else:
                    coords = coords.reshape(-1)
                    if len(coords) < 4:
                        continue
                    if len(coords) >= 8:
                        x0, x1 = coords[0::2].min(), coords[0::2].max()
                        y0, y1 = coords[1::2].min(), coords[1::2].max()
                    else:
                        x0, y0, x1, y1 = coords[:4]
                score = float(scores[index]) if index < len(scores) else 0.0
                if max(abs(x0), abs(y0), abs(x1), abs(y1)) > 100_000:
                    continue
                rows.append({
                    "text": text,
                    "confidence": max(0.0, min(100.0, score * 100.0)),
                    "bbox": [int(x0), int(y0), int(x1), int(y1)],
                    "engine": "paddleocr-pp-ocrv5-ar",
                })
            except (TypeError, ValueError, IndexError):
                continue
    return rows


def _recognize(image: np.ndarray) -> list[dict]:
    model = _get_model()
    return _rows_from_result(model.predict(image))


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "service": "Got-pdf remote PaddleOCR worker",
        "engine": "PaddleOCR PP-OCRv5 Arabic",
        "device": "cpu",
        "cpu_threads": CPU_THREADS,
        "model_loaded": _model is not None,
        "authenticated": bool(APP_KEY),
        "max_upload_mb": MAX_UPLOAD_MB,
    }


@app.post("/api/ocr/image")
async def ocr_image(
    file: UploadFile = File(...),
    language: str = Form("ara+eng"),
    authorization: str | None = Header(default=None),
):
    if not APP_KEY:
        raise HTTPException(503, "Worker API key is not configured.")
    if authorization != "Bearer " + APP_KEY:
        raise HTTPException(401, "Invalid worker credentials.")
    if language not in {"ara", "eng", "ara+eng"}:
        raise HTTPException(422, "Unsupported OCR language.")
    data = await file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if not data or len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, "Image is empty or exceeds the upload limit.")
    try:
        with Image.open(io.BytesIO(data)) as source:
            source = ImageOps.exif_transpose(source)
            source.load()
            if source.width * source.height > MAX_PIXELS:
                raise HTTPException(413, "Image dimensions exceed the processing limit.")
            rgb = source.convert("RGB")
            width, height = rgb.size
            image = np.asarray(rgb)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(415, "Unsupported or invalid image.") from exc
    try:
        await asyncio.wait_for(_inference_lock.acquire(), timeout=90)
    except asyncio.TimeoutError as exc:
        raise HTTPException(503, "PaddleOCR worker is busy.") from exc
    try:
        lines = await run_in_threadpool(_recognize, image)
    except Exception as exc:
        raise HTTPException(503, "PaddleOCR inference failed: " + str(exc)[:240]) from exc
    finally:
        _inference_lock.release()
    return {
        "engine": "PaddleOCR PP-OCRv5 Arabic",
        "image_width": width,
        "image_height": height,
        "lines": lines,
        "tables": [],
    }
