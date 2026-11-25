"""Explainable visual-style estimates for OCR text regions.

These are measurements, not claims that a line is handwritten or that a font
has been identified. The editor can use them as starting hints and let users
override them.
"""
from __future__ import annotations

import cv2
import numpy as np


def _hex_color(rgb: np.ndarray) -> str:
    values = np.clip(np.rint(rgb), 0, 255).astype(int).tolist()
    return "#" + "".join(f"{value:02x}" for value in values)


def analyze_text_style(image: np.ndarray, bbox: list[int] | tuple[int, ...]) -> dict:
    """Estimate ink/background colors, contrast and stroke irregularity in a box."""
    if image is None or not isinstance(image, np.ndarray) or image.ndim not in (2, 3):
        raise ValueError("صورة غير صالحة لتحليل نمط الكتابة.")
    if len(bbox) != 4:
        raise ValueError("حدود منطقة النص غير صالحة.")
    height, width = image.shape[:2]
    try:
        x0, y0, x1, y1 = (int(round(float(v))) for v in bbox)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("حدود منطقة النص غير صالحة.") from exc
    x0, x1 = max(0, min(width, x0)), max(0, min(width, x1))
    y0, y1 = max(0, min(height, y0)), max(0, min(height, y1))
    if x1 - x0 < 3 or y1 - y0 < 3:
        raise ValueError("منطقة النص صغيرة جدًا لتحليل نمطها.")

    pad = max(3, min(16, round(min(x1 - x0, y1 - y0) * 0.18)))
    xa, xb = max(0, x0 - pad), min(width, x1 + pad)
    ya, yb = max(0, y0 - pad), min(height, y1 + pad)
    crop = image[ya:yb, xa:xb]
    if crop.size == 0:
        raise ValueError("تعذّر قراءة منطقة النص.")
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB) if crop.ndim == 3 else cv2.cvtColor(crop, cv2.COLOR_GRAY2RGB)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    inner = gray[y0 - ya:y1 - ya, x0 - xa:x1 - xa]
    border = np.concatenate((gray[:max(1, y0-ya), :].ravel(),
                             gray[min(gray.shape[0]-1, y1-ya):, :].ravel(),
                             gray[:, :max(1, x0-xa)].ravel(),
                             gray[:, min(gray.shape[1]-1, x1-xa):].ravel()))
    if border.size < 8:
        border = gray.ravel()
    # A robust local paper/background estimate; the ink estimate uses the
    # darker tail so colored ink is retained rather than forced to black.
    background_luma = float(np.median(border))
    delta = np.abs(inner.astype(np.float32) - background_luma)
    threshold = max(18.0, float(np.percentile(delta, 55)))
    ink_mask = delta >= threshold
    if int(ink_mask.sum()) < 3:
        ink_mask = inner < max(180.0, background_luma - 20.0)
    bg_pixels = rgb[:max(1, y0-ya), :, :].reshape(-1, 3)
    if bg_pixels.size == 0:
        bg_pixels = rgb.reshape(-1, 3)
    bg = np.median(bg_pixels, axis=0)
    ink_pixels = rgb[y0-ya:y1-ya, x0-xa:x1-xa][ink_mask]
    ink = np.median(ink_pixels, axis=0) if len(ink_pixels) else np.array([0, 0, 0])
    contrast = float(abs(np.mean(ink) - np.mean(bg)))
    density = float(ink_mask.mean())
    components = cv2.connectedComponentsWithStats(ink_mask.astype(np.uint8), 8)[2]
    areas = components[1:, cv2.CC_STAT_AREA] if len(components) > 1 else np.array([], dtype=np.int32)
    useful = areas[areas >= 2]
    if useful.size >= 3:
        irregularity = float(np.std(useful) / max(1.0, np.mean(useful)))
    else:
        irregularity = 0.0
    # Never label handwriting as fact: this only signals that the region may
    # need manual font/style selection rather than automatic font substitution.
    handwriting_candidate = bool(useful.size >= 4 and irregularity > 1.15 and density < 0.42)
    return {
        "ink_color": _hex_color(ink),
        "background_color": _hex_color(bg),
        "contrast": round(min(255.0, contrast), 2),
        "ink_density": round(density, 4),
        "component_count": int(useful.size),
        "component_size_variation": round(min(10.0, irregularity), 3),
        "handwriting_candidate": handwriting_candidate,
        "style_confidence": round(min(0.95, max(0.0, (irregularity - 0.8) / 3.0)), 3),
        "analysis": "visual_heuristic",
    }
