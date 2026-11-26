"""Explainable document layout analysis for OCR line boxes.

The module preserves OCR's original line array and adds an explicit reading-order
index so clients can render/reconstruct multi-column pages without losing provenance.
"""
from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any


def _valid_box(item: dict[str, Any], width: int, height: int) -> list[float] | None:
    box = item.get("bbox")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    x0, x1 = sorted((max(0.0, min(float(width), x0)), max(0.0, min(float(width), x1))))
    y0, y1 = sorted((max(0.0, min(float(height), y0)), max(0.0, min(float(height), y1))))
    return [x0, y0, x1, y1] if x1 > x0 and y1 > y0 else None


def _direction(text: str) -> tuple[str, float]:
    arabic = sum(0x0600 <= ord(char) <= 0x06ff for char in text)
    latin = sum("a" <= char.lower() <= "z" for char in text)
    total = arabic + latin
    if not total:
        return "unknown", 0.0
    return ("rtl" if arabic >= latin else "ltr"), abs(arabic - latin) / total


def _find_columns(
    lines: list[dict[str, Any]], width: int
) -> tuple[list[list[int]], float | None]:
    """Find a strong vertical whitespace gutter; return columns and gutter center."""
    all_indices = list(range(len(lines)))
    if len(lines) < 4 or width < 100:
        return [all_indices], None
    eligible = []
    for index, line in enumerate(lines):
        x0, _, x1, _ = line["_box"]
        if x1 - x0 <= width * 0.72:
            eligible.append((index, x0, x1))
    if len(eligible) < 4:
        return [all_indices], None
    occupancy = [0] * width
    for _, x0, x1 in eligible:
        left, right = max(0, int(x0)), min(width, int(x1 + 0.999))
        for x in range(left, right):
            occupancy[x] += 1
    min_gap = max(24, int(width * 0.055))
    best = None
    start = None
    for x, count in enumerate(occupancy + [1]):
        if count == 0 and start is None:
            start = x
        elif count != 0 and start is not None:
            if x - start >= min_gap:
                candidate = (x - start, start, x)
                if best is None or candidate[0] > best[0]:
                    best = candidate
            start = None
    if best is None:
        return [all_indices], None
    _, gap_start, gap_end = best
    split = (gap_start + gap_end) / 2
    left, right = [], []
    for index, line in enumerate(lines):
        x0, _, x1, _ = line["_box"]
        if x1 <= split:
            left.append(index)
        elif x0 >= split:
            right.append(index)
        # Lines crossing the gutter are page-spanning blocks, not column members.
    if len(left) < 2 or len(right) < 2:
        return [all_indices], None
    return [left, right], split


def analyze_layout(
    lines: list[dict[str, Any]], width: int, height: int,
    tables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return layout metadata, preserving original OCR line order and content."""
    width, height = max(1, int(width)), max(1, int(height))
    prepared = []
    for index, source in enumerate(lines or []):
        if not isinstance(source, dict):
            continue
        box = _valid_box(source, width, height)
        if box is None:
            continue
        item = dict(source)
        item["_box"] = box
        item["_index"] = index
        item["direction"], item["direction_confidence"] = _direction(str(item.get("text", "")))
        prepared.append(item)

    directions = [item["direction"] for item in prepared if item["direction"] != "unknown"]
    rtl_count, ltr_count = directions.count("rtl"), directions.count("ltr")
    page_direction = "rtl" if rtl_count >= ltr_count and rtl_count else ("ltr" if ltr_count else "unknown")
    direction_confidence = max(rtl_count, ltr_count) / len(directions) if directions else 0.0

    columns, split = _find_columns(prepared, width)
    if len(columns) == 2:
        columns.sort(
            key=lambda group: min(prepared[i]["_box"][0] for i in group),
            reverse=page_direction == "rtl",
        )
    column_ids: dict[int, int] = {}
    for column_id, group in enumerate(columns, start=1):
        for index in group:
            column_ids[index] = column_id

    spanning = []
    if split is not None:
        spanning = [
            i for i, item in enumerate(prepared)
            if item["_box"][0] < split < item["_box"][2]
        ]
    # A full-width title above the columns is read first. Column content is then
    # read top-to-bottom in RTL/LTR column order; remaining spanning blocks follow.
    first_column_y = min(
        (min(prepared[i]["_box"][1] for i in group) for group in columns if group),
        default=0.0,
    )
    top_spanning = [i for i in spanning if prepared[i]["_box"][3] <= first_column_y + 1]
    other_spanning = [i for i in spanning if i not in top_spanning]
    reading_indices = sorted(top_spanning, key=lambda i: prepared[i]["_box"][1])
    for group in columns:
        reading_indices.extend(sorted(
            group,
            key=lambda i: (
                prepared[i]["_box"][1],
                -prepared[i]["_box"][0] if page_direction == "rtl" else prepared[i]["_box"][0],
            ),
        ))
    reading_indices.extend(sorted(other_spanning, key=lambda i: prepared[i]["_box"][1]))
    # Map prepared indices to positions in the original returned line array.
    original_indices = [item["_index"] for item in prepared]
    output_position = {original_index: pos for pos, original_index in enumerate(original_indices)}
    reading_order = [output_position[prepared[i]["_index"]] for i in reading_indices]

    heights = [item["_box"][3] - item["_box"][1] for item in prepared]
    typical_height = median(heights) if heights else 1.0
    table_boxes = [table.get("bbox") for table in (tables or []) if isinstance(table, dict)]
    enriched, regions = [], []
    for item in prepared:
        x0, y0, x1, y1 = item["_box"]
        line_height = y1 - y0
        center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
        in_table = any(
            isinstance(box, (list, tuple)) and len(box) == 4
            and box[0] <= center_x <= box[2] and box[1] <= center_y <= box[3]
            for box in table_boxes
        )
        text = str(item.get("text", "")).strip()
        if in_table:
            region, confidence = "table", 0.92
        elif item["_index"] in spanning and len(text) <= 120:
            region, confidence = "heading", 0.7
        elif line_height >= typical_height * 1.15 and len(text) <= 100:
            region, confidence = "heading", min(0.9, 0.62 + (line_height / typical_height - 1.15) * 0.3)
        elif y0 >= height * 0.88:
            region, confidence = "footer", 0.72
        elif y1 <= height * 0.12 and len(text) <= 90:
            region, confidence = "header", 0.68
        else:
            region, confidence = "body", 0.66
        clean = {key: value for key, value in item.items() if not key.startswith("_")}
        clean.update({
            "region": region,
            "region_confidence": round(float(confidence), 3),
            "column": 0 if item["_index"] in spanning else column_ids.get(item["_index"], 1),
            "reading_order": reading_order.index(output_position[item["_index"]]) + 1,
        })
        enriched.append((item["_index"], clean))
        regions.append(region)

    enriched.sort(key=lambda pair: pair[0])
    return {
        "direction": page_direction,
        "direction_confidence": round(direction_confidence, 3),
        "column_count": len(columns),
        "regions": dict(Counter(regions)),
        "reading_order": reading_order,
        "lines": [item for _, item in enriched],
        "analysis": "heuristic",
    }


def attach_table_regions(result: dict[str, Any], tables: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Re-apply layout labels after table detection, preserving OCR response schema."""
    if not isinstance(result, dict):
        return result
    try:
        width, height = int(result.get("image_width", 0)), int(result.get("image_height", 0))
    except (TypeError, ValueError):
        return result
    if width < 1 or height < 1:
        return result
    layout = analyze_layout(result.get("lines") or [], width, height, tables=tables or [])
    enriched = dict(result)
    enriched["lines"] = layout["lines"]
    enriched["layout"] = {key: value for key, value in layout.items() if key != "lines"}
    return enriched
