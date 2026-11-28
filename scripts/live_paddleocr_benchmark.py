#!/usr/bin/env python3
"""Benchmark PaddleOCR PP-OCRv5 Arabic on two public, authentic document images."""
from __future__ import annotations
import hashlib, json, re, tarfile, tempfile, time, unicodedata
from pathlib import Path
import requests
import pymupdf
from PIL import Image, ImageOps
import pytesseract
from paddleocr import PaddleOCR

PDF_URL = "https://dlp.dubai.gov.ae/Legislation%20Ar%20Reference/2025/%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%B1%D9%82%D9%85%20(7)%20%D9%84%D8%B3%D9%86%D8%A9%202025%20%D8%A8%D8%B4%D8%A3%D9%86%20%D8%AA%D9%86%D8%B8%D9%8A%D9%85%20%D9%85%D8%B2%D8%A7%D9%88%D9%84%D8%A9%20%D8%A3%D9%86%D8%B4%D8%B7%D8%A9%20%D8%A7%D9%84%D9%85%D9%82%D8%A7%D9%88%D9%84%D8%A7%D8%AA.pdf"
NOD_URL = "https://zenodo.org/api/records/5068735/files/yarmouk_01_col.tar.lzma/content"
NOD_MD5 = "a845e80b66fea3507ad39f3c07684ff6"

def normalize(value):
    value = unicodedata.normalize("NFC", value or "")
    value = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", value)
    return re.sub(r"\s+", "", value)

def cer(reference, candidate):
    a, b = normalize(reference), normalize(candidate)
    if not a:
        return None
    previous = list(range(len(b) + 1))
    for i, char in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (char != other)))
        previous = current
    return round(previous[-1] / len(a), 4)

def fetch(url, path):
    response = requests.get(url, timeout=(20, 180),
                            headers={"User-Agent": "GotPDF-Paddle-benchmark/1.0"})
    response.raise_for_status()
    path.write_bytes(response.content)
    return response.content

def prepare(image):
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
    return image

def unpack_result(result):
    data = getattr(result, "json", None)
    if callable(data):
        data = data()
    if not isinstance(data, dict):
        data = {}
    data = data.get("res", data)
    texts = data.get("rec_texts") or []
    boxes = data.get("rec_boxes") or data.get("rec_polys") or []
    scores = data.get("rec_scores") or []
    rows = []
    for index, text in enumerate(texts):
        if not str(text).strip():
            continue
        box = boxes[index] if index < len(boxes) else []
        try:
            coords = [float(v) for v in box]
            if len(coords) >= 8:
                xs, ys = coords[0::2], coords[1::2]
                x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            elif len(coords) >= 4:
                x1, y1, x2, y2 = coords[:4]
            else:
                x1 = y1 = x2 = y2 = 0
        except Exception:
            x1 = y1 = x2 = y2 = 0
        rows.append({"text": str(text), "x": x1, "y": (y1+y2)/2,
                     "score": float(scores[index]) if index < len(scores) else None})
    # Group by approximate line, then read Arabic lines right-to-left.
    rows.sort(key=lambda row: row["y"])
    bands = []
    for row in rows:
        if not bands or abs(row["y"] - bands[-1]["y"]) > 16:
            bands.append({"y": row["y"], "rows": [row]})
        else:
            bands[-1]["rows"].append(row)
            bands[-1]["y"] = sum(x["y"] for x in bands[-1]["rows"]) / len(bands[-1]["rows"])
    lines = []
    for band in bands:
        line = band["rows"]
        ar = sum(0x600 <= ord(c) <= 0x6ff for r in line for c in r["text"])
        en = sum(c.isascii() and c.isalpha() for r in line for c in r["text"])
        line.sort(key=lambda row: row["x"], reverse=ar >= en)
        lines.append(" ".join(row["text"] for row in line))
    confidence = [row["score"] for row in rows if row["score"] is not None]
    return "\n".join(lines), len(lines), (sum(confidence)/len(confidence) if confidence else None)

def main():
    report = {"engine": "PaddleOCR PP-OCRv5 Arabic", "language": "ar",
              "tests": [], "environment": {}}
    try:
        import paddle, paddleocr
        report["environment"] = {"paddle_version": paddle.__version__,
                                 "paddleocr_version": getattr(paddleocr, "__version__", "unknown"),
                                 "tesseract_version": str(pytesseract.get_tesseract_version()),
                                 "tesseract_languages": pytesseract.get_languages(config="")}
    except Exception:
        pass
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        inputs = root / "inputs"
        inputs.mkdir()
        cases = {}
        try:
            pdf_path = root / "dubai-law.pdf"
            fetch(PDF_URL, pdf_path)
            doc = pymupdf.open(pdf_path)
            page = doc[0]
            pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            image = prepare(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
            image_path = inputs / "dubai_law_page1.png"
            image.save(image_path)
            cases["real_dubai_law_page1"] = {"path": image_path, "reference": page.get_text("text")}
            doc.close()
        except Exception as exc:
            report["tests"].append({"name": "real_dubai_law_page1", "status": "failed",
                                    "error": f"{type(exc).__name__}: {str(exc)[:500]}"})
        try:
            archive = root / "nod-scans.tar.lzma"
            raw = fetch(NOD_URL, archive)
            if hashlib.md5(raw).hexdigest() != NOD_MD5:
                raise ValueError("NOD archive checksum mismatch")
            with tarfile.open(archive, "r:xz") as tar:
                members = [m for m in tar.getmembers() if m.isfile()
                           and Path(m.name).suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}]
                if not members:
                    raise ValueError("No scan found in the public archive")
                member = members[0]
                stream = tar.extractfile(member)
                if stream is None:
                    raise ValueError("Could not read scan")
                image = prepare(Image.open(stream))
            image_path = inputs / "nod_real_scan.png"
            image.save(image_path)
            cases["real_nod_scanned_page"] = {"path": image_path, "source_member": member.name}
        except Exception as exc:
            report["tests"].append({"name": "real_nod_scanned_page", "status": "failed",
                                    "error": f"{type(exc).__name__}: {str(exc)[:500]}"})
        if cases:
            started = time.perf_counter()
            try:
                # Arabic is explicitly mapped to the PP-OCRv5 Arabic recognizer.
                ocr = PaddleOCR(ocr_version="PP-OCRv5", lang="ar", device="cpu",
                                enable_mkldnn=False, cpu_threads=2,
                                use_doc_orientation_classify=False,
                                use_doc_unwarping=False,
                                use_textline_orientation=False)
                init_seconds = time.perf_counter() - started
                for name, meta in cases.items():
                    # Both engines process the same resized input image.
                    paddle_started = time.perf_counter()
                    predictions = ocr.predict(str(meta["path"]))
                    texts, line_count, confidence = [], 0, None
                    for prediction in predictions:
                        text, count, score = unpack_result(prediction)
                        if text:
                            texts.append(text)
                            line_count += count
                        if score is not None:
                            confidence = score if confidence is None else (confidence + score) / 2
                    paddle_text = "\n".join(texts)
                    paddle_item = {"name": name, "engine": "paddleocr_ppocrv5_ar",
                                   "status": "passed" if paddle_text else "failed",
                                   "lines": line_count, "chars": len(paddle_text),
                                   "arabic_chars": sum(0x600 <= ord(c) <= 0x6ff for c in paddle_text),
                                   "seconds": round(time.perf_counter() - paddle_started, 2),
                                   "mean_recognition_confidence": round(confidence, 4) if confidence is not None else None,
                                   "text": paddle_text[:12000]}
                    if "reference" in meta:
                        paddle_item["cer_vs_embedded_pdf_text"] = cer(meta["reference"], paddle_text)
                    if "source_member" in meta:
                        paddle_item["source_member"] = meta["source_member"]
                    report["tests"].append(paddle_item)

                    tess_started = time.perf_counter()
                    with Image.open(meta["path"]) as sample:
                        tess_text = pytesseract.image_to_string(sample, lang="ara+eng", config="--psm 6")
                    tess_item = {"name": name, "engine": "tesseract_ara_eng",
                                 "status": "passed" if tess_text.strip() else "failed",
                                 "lines": len([line for line in tess_text.splitlines() if line.strip()]),
                                 "chars": len(tess_text),
                                 "arabic_chars": sum(0x600 <= ord(ch) <= 0x6ff for ch in tess_text),
                                 "seconds": round(time.perf_counter() - tess_started, 2),
                                 "text": tess_text[:12000]}
                    if "reference" in meta:
                        tess_item["cer_vs_embedded_pdf_text"] = cer(meta["reference"], tess_text)
                    if "source_member" in meta:
                        tess_item["source_member"] = meta["source_member"]
                    report["tests"].append(tess_item)
                report["model_initialization_seconds"] = round(init_seconds, 2)
                report["runtime_seconds"] = round(time.perf_counter() - started, 2)
            except Exception as exc:
                report["runtime_seconds"] = round(time.perf_counter() - started, 2)
                report["error"] = f"{type(exc).__name__}: {str(exc)[:1800]}"
                for name in cases:
                    report["tests"].append({"name": name, "status": "failed", "error": report["error"]})
    Path("paddle-live-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    comparable = [item for item in report["tests"] if item.get("cer_vs_embedded_pdf_text") is not None]
    report["comparison_summary"] = {}
    for engine in sorted({item["engine"] for item in comparable}):
        rows = [item for item in comparable if item["engine"] == engine]
        report["comparison_summary"][engine] = {
            "samples": len(rows),
            "mean_cer": round(sum(item["cer_vs_embedded_pdf_text"] for item in rows) / len(rows), 4),
            "mean_seconds": round(sum(item["seconds"] for item in rows) / len(rows), 2),
        }
    Path("paddle-live-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["tests"] or any(item.get("status") != "passed" for item in report["tests"]):
        raise SystemExit("One or more real-file OCR engine tests failed; report saved")

if __name__ == "__main__":
    main()
