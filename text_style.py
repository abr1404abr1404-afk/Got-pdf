"""Explainable visual-style estimates for OCR text regions.

Measurements are hints for reconstruction, not font identification. In particular,
a geometric heuristic must never be presented as proof that text is handwritten.
"""
from __future__ import annotations

import cv2
import numpy as np


def _hex_color(rgb: np.ndarray) -> str:
    values = np.clip(np.rint(rgb), 0, 255).astype(int).tolist()
    return "#" + "".join(f"{value:02x}" for value in values)


def _script_hint(text: str | None) -> str:
    value = text or ""
    arabic = sum("\u0600" <= ch <= "\u06ff" for ch in value)
    latin = sum(("a" <= ch.lower() <= "z") for ch in value)
    if arabic and latin:
        return "mixed"
    if arabic:
        return "arabic"
    if latin:
        return "latin"
    return "unknown"


def analyze_text_style(
    image: np.ndarray,
    bbox: list[int] | tuple[int, ...],
    text: str | None = None,
) -> dict:
    """Estimate local ink, geometry and stroke features for a detected text box."""
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
    border_parts = [
        gray[:max(1, y0 - ya), :].ravel(),
        gray[min(gray.shape[0] - 1, y1 - ya):, :].ravel(),
        gray[:, :max(1, x0 - xa)].ravel(),
        gray[:, min(gray.shape[1] - 1, x1 - xa):].ravel(),
    ]
    border = np.concatenate([part for part in border_parts if part.size])
    if border.size < 8:
        border = gray.ravel()

    background_luma = float(np.median(border))
    delta = np.abs(inner.astype(np.float32) - background_luma)
    threshold = max(18.0, float(np.percentile(delta, 55)))
    ink_mask = delta >= threshold
    if int(ink_mask.sum()) < 3:
        ink_mask = inner < max(180.0, background_luma - 20.0)

    # Estimate colors from the local page, preserving colored pen/print ink.
    bg_pixels = np.concatenate([
        rgb[:max(1, y0 - ya), :, :].reshape(-1, 3),
        rgb[min(rgb.shape[0] - 1, y1 - ya):, :, :].reshape(-1, 3),
    ], axis=0)
    if bg_pixels.size == 0:
        bg_pixels = rgb.reshape(-1, 3)
    bg = np.median(bg_pixels, axis=0)
    ink_pixels = rgb[y0 - ya:y1 - ya, x0 - xa:x1 - xa][ink_mask]
    ink = np.median(ink_pixels, axis=0) if len(ink_pixels) else np.array([0, 0, 0])
    contrast = float(abs(np.mean(ink) - np.mean(bg)))
    density = float(ink_mask.mean())

    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink_mask.astype(np.uint8), connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA] if count > 1 else np.array([], dtype=np.int32)
    useful = areas[areas >= 2]
    irregularity = float(np.std(useful) / max(1.0, np.mean(useful))) if useful.size >= 3 else 0.0

    ys, xs = np.where(ink_mask)
    line_angle = 0.0
    stroke_width = 0.0
    baseline_ratio = 0.0
    if len(xs) >= 8:
        points = np.column_stack((xs, ys)).astype(np.float32).reshape(-1, 1, 2)
        vx, vy, _, _ = cv2.fitLine(points, cv2.DIST_L2, 0, 0.01, 0.01)
        line_angle = float(np.degrees(np.arctan2(float(vy), float(vx))))
        # Keep the estimate descriptive; text boxes can contain multiple glyph rows.
        if line_angle > 45:
            line_angle -= 90
        elif line_angle < -45:
            line_angle += 90
        baseline_ratio = float(np.percentile(ys, 95) / max(1, inner.shape[0]))
        distance = cv2.distanceTransform(ink_mask.astype(np.uint8), cv2.DIST_L2, 3)
        radii = distance[ink_mask]
        if radii.size:
            stroke_width = float(2.0 * np.percentile(radii, 55))

    handwriting_candidate = bool(useful.size >= 4 and irregularity > 1.15 and density < 0.42)
    if len(xs) < 8 or contrast < 12:
        style_classification = "uncertain"
    elif handwriting_candidate:
        style_classification = "handwriting_possible"
    elif irregularity > 2.0 and density < 0.5:
        style_classification = "decorative_or_irregular"
    else:
        style_classification = "printed_or_regular"

    box_width, box_height = x1 - x0, y1 - y0
    return {
        "ink_color": _hex_color(ink),
        "background_color": _hex_color(bg),
        "contrast": round(min(255.0, contrast), 2),
        "ink_density": round(density, 4),
        "component_count": int(useful.size),
        "component_size_variation": round(min(10.0, irregularity), 3),
        "handwriting_candidate": handwriting_candidate,
        "style_classification": style_classification,
        "script_hint": _script_hint(text),
        "line_angle_degrees": round(max(-45.0, min(45.0, line_angle)), 2),
        "estimated_stroke_width_px": round(min(100.0, stroke_width), 2),
        "baseline_ratio": round(max(0.0, min(1.0, baseline_ratio)), 3),
        "region_width_px": box_width,
        "region_height_px": box_height,
        "region_aspect_ratio": round(box_width / max(1, box_height), 3),
        "style_confidence": round(min(0.95, max(0.0, (irregularity - 0.8) / 3.0)), 3),
        "analysis": "visual_heuristic",
        "limitations": "هذه تقديرات بصرية وليست تحديدًا مؤكدًا لنوع الخط أو كونه خط يد.",
    }
