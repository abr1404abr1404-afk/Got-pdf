#!/usr/bin/env python3
"""Benchmark the deployed API on authentic public Arabic PDFs and scans.

Each case is isolated so one slow OCR request does not prevent the remaining
image, scan, and PDF-to-DOCX checks from running. Results are always written
to live-ocr-results.json for inspection, including failures and timeouts.
"""
from __future__ import annotations
import hashlib, json, os, re, tarfile, tempfile, unicodedata
from pathlib import Path
import sys

# Running a script from scripts/ places that directory, not the repository
# root, at sys.path[0]. Add the project root so service modules can be tested.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests
import pymupdf

BASE = os.environ.get("OCR_API_BASE", "https://got-pdf.onrender.com").rstrip("/")
SOURCES = [
    ("dubai_law", "https://dlp.dubai.gov.ae/Legislation%20Ar%20Reference/2025/%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%B1%D9%82%D9%85%20(7)%20%D9%84%D8%B3%D9%86%D8%A9%202025%20%D8%A8%D8%B4%D8%A3%D9%86%20%D8%AA%D9%86%D8%B8%D9%8A%D9%85%20%D9%85%D8%B2%D8%A7%D9%88%D9%84%D8%A9%20%D8%A3%D9%86%D8%B4%D8%B7%D8%A9%20%D8%A7%D9%84%D9%85%D9%82%D8%A7%D9%88%D9%84%D8%A7%D8%AA.pdf"),
    ("mohre_labour_law", "https://mohre.gov.ae/assets/download/43e39236/%D9%85%D8%B1%D8%B3%D9%88%D9%85%20%D8%A8%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%A7%D8%AA%D8%AD%D8%A7%D8%AF%D9%8A%20%D8%B1%D9%82%D9%85%2033%20%D9%84%D8%B3%D9%86%D8%A9%202021%20%D8%A8%D8%B4%D8%A3%D9%86%20%D8%AA%D9%86%D8%B8%D9%8A%D9%85%20%D8%B9%D9%84%D8%A7%D9%82%D8%A7%D8%AA%20%D8%A7%D9%84%D8%B9%D9%85%D9%84%20%D9%88%D8%AA%D8%B9%D8%AF%D9%8A%D9%84%D8%A7%D8%AA%D9%87_638990570577815564.pdf.aspx"),
]
NOD_URL = "https://zenodo.org/api/records/5068735/files/yarmouk_01_col.tar.lzma/content"
NOD_MD5 = "a845e80b66fea3507ad39f3c07684ff6"

def norm(value):
    value = unicodedata.normalize("NFC", value or "")
    value = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", value)
    return re.sub(r"\s+", "", value)

def cer(reference, candidate):
    a, b = norm(reference), norm(candidate)
    if not a:
        return None
    prev = list(range(len(b) + 1))
    for i, char in enumerate(a, 1):
        cur = [i]
        for j, other in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (char != other)))
        prev = cur
    return round(prev[-1] / len(a), 4)

def download(url, path):
    response = requests.get(url, timeout=(20, 120), headers={"User-Agent": "GotPDF-live-OCR-benchmark/2.0"})
    response.raise_for_status()
    path.write_bytes(response.content)
    return response.content

def api_post(out, name, endpoint, path, content_type, data=None, timeout=120):
    try:
        with path.open("rb") as handle:
            response = requests.post(
                BASE + endpoint,
                files={"file": (path.name, handle, content_type)},
                data=data or {},
                timeout=(15, timeout),
            )
        if response.status_code >= 400:
            out["tests"].append({"name": name, "status": "failed", "http_status": response.status_code,
                                 "response_body": response.text[:1200]})
            return None
        payload = response.json()
        out["tests"].append({"name": name, "status": "passed", "http_status": response.status_code})
        return payload
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        out["tests"].append({"name": name, "status": "failed",
                             "http_status": response.status_code if response is not None else None,
                             "response_body": response.text[:1200] if response is not None else None,
                             "error": f"{type(exc).__name__}: {str(exc)[:500]}"})
    except (ValueError, KeyError, TypeError) as exc:
        out["tests"].append({"name": name, "status": "failed", "error": f"Invalid API response: {str(exc)[:300]}"})
    return None

def arabic_count(value):
    return sum("\u0600" <= char <= "\u06ff" for char in value)

def main():
    out = {"api_base": BASE, "sources": [], "tests": [], "started_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
    try:
        health = requests.get(BASE + "/api/health", timeout=(15, 60))
        health.raise_for_status()
        out["health_status"] = health.status_code
        out["health"] = health.json()
    except requests.RequestException as exc:
        out["health_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        Path("live-ocr-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit("Render health check failed; details saved to artifact.")

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for name, url in SOURCES:
            pdf_path = root / f"{name}.pdf"
            try:
                raw = download(url, pdf_path)
                if not raw.startswith(b"%PDF"):
                    raise ValueError("Publisher URL did not return a PDF")
                doc = pymupdf.open(pdf_path)
                out["sources"].append({"name": name, "url": url, "pages": doc.page_count, "bytes": len(raw)})
                sample = pymupdf.open()
                sample.insert_pdf(doc, from_page=0, to_page=0)
                sample_path = root / f"{name}_one_page.pdf"
                sample.save(sample_path)
                page = doc.load_page(0)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
                image_path = root / f"{name}_page1.png"
                pix.save(image_path)
                ground = page.get_text("text") or ""

                # Real PDF -> DOCX conversion and quality inspection run locally
                # in CI, independently from the Render OCR service.
                try:
                    from pdf_to_docx import convert_pdf_to_docx, analyze_pdf_docx_quality
                    docx_bytes = convert_pdf_to_docx(sample_path.read_bytes())
                    if not docx_bytes.startswith(b"PK"):
                        raise ValueError("DOCX ZIP signature is invalid")
                    quality = analyze_pdf_docx_quality(sample_path.read_bytes(), docx_bytes)
                    from docx import Document
                    import io
                    word_doc = Document(io.BytesIO(docx_bytes))
                    word_text = "\n".join(p.text for p in word_doc.paragraphs)
                    word_test = {"name": name + "_real_pdf_to_docx", "status": "passed",
                                 "docx_bytes": len(docx_bytes), "paragraphs": len(word_doc.paragraphs),
                                 "tables": len(word_doc.tables), "arabic_chars": arabic_count(word_text),
                                 "quality": quality}
                    if quality.get("analysis_status") == "ok" and quality.get("text_coverage_percent", 0) < 65:
                        word_test["status"] = "failed"
                        word_test["error"] = "DOCX text coverage below 65%"
                    out["tests"].append(word_test)
                except Exception as exc:
                    out["tests"].append({"name": name + "_real_pdf_to_docx", "status": "failed",
                                         "error": f"{type(exc).__name__}: {str(exc)[:500]}"})
                pdf_payload = api_post(out, name + "_real_pdf_ocr", "/api/ocr/pdf", sample_path,
                                        "application/pdf", {"language": "ara+eng", "dpi": "96"}, timeout=150)
                if pdf_payload is not None:
                    extracted = "\n".join(line.get("text", "") for pg in pdf_payload.get("pages", [])
                                           for line in pg.get("ocr", {}).get("lines", []))
                    test = out["tests"][-1]
                    test.update({"pages": pdf_payload.get("page_count"), "ground_truth_chars": len(ground),
                                 "ocr_chars": len(extracted), "arabic_chars": arabic_count(extracted),
                                 "cer_vs_embedded_pdf_text": cer(ground, extracted)})
                    if arabic_count(extracted) == 0:
                        test["status"] = "failed"
                        test["error"] = "OCR returned no Arabic characters"

                image_payload = api_post(out, name + "_real_page_image_ocr", "/api/ocr/image", image_path,
                                          "image/png", {"language": "ara+eng"}, timeout=150)
                if image_payload is not None:
                    extracted = "\n".join(line.get("text", "") for line in image_payload.get("lines", []))
                    test = out["tests"][-1]
                    test.update({"ocr_chars": len(extracted), "arabic_chars": arabic_count(extracted),
                                 "lines": len(image_payload.get("lines", []))})
                    if arabic_count(extracted) == 0:
                        test["status"] = "failed"
                        test["error"] = "Image OCR returned no Arabic characters"

                sample.close()
                doc.close()
            except Exception as exc:
                out["sources"].append({"name": name, "status": "download_or_parse_failed",
                                       "error": f"{type(exc).__name__}: {str(exc)[:500]}"})

        # Authentic scanned page from the Yarmouk/NOD research collection.
        archive = root / "nod_scans.tar.lzma"
        try:
            raw = download(NOD_URL, archive)
            if hashlib.md5(raw).hexdigest() != NOD_MD5:
                raise ValueError("NOD archive checksum mismatch")
            chosen = None
            with tarfile.open(archive, "r:xz") as tar:
                members = [m for m in tar.getmembers() if m.isfile() and Path(m.name).suffix.lower() in
                           {".png", ".jpg", ".jpeg", ".tif", ".tiff"}]
                if not members:
                    raise ValueError("No raster scan found in NOD archive")
                chosen = members[0]
                extracted_file = tar.extractfile(chosen)
                if extracted_file is None:
                    raise ValueError("Could not read selected scan")
                scan_path = root / ("nod_real_scan" + Path(chosen.name).suffix.lower())
                scan_path.write_bytes(extracted_file.read())
            payload = api_post(out, "nod_real_scanned_page_ocr", "/api/ocr/image", scan_path,
                               "image/tiff" if scan_path.suffix == ".tif" else "image/jpeg",
                               {"language": "ara+eng"}, timeout=150)
            if payload is not None:
                text_out = "\n".join(line.get("text", "") for line in payload.get("lines", []))
                test = out["tests"][-1]
                test.update({"source_member": chosen.name, "ocr_chars": len(text_out),
                             "arabic_chars": arabic_count(text_out), "lines": len(payload.get("lines", []))})
                if arabic_count(text_out) == 0:
                    test["status"] = "failed"
                    test["error"] = "Scanned image OCR returned no Arabic characters"
        except Exception as exc:
            out["tests"].append({"name": "nod_real_scanned_page_ocr", "status": "failed",
                                 "error": f"{type(exc).__name__}: {str(exc)[:500]}"})

    out["finished_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    Path("live-ocr-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    failed = [item for item in out["tests"] if item.get("status") != "passed"]
    if failed:
        raise SystemExit(f"{len(failed)} real-file test(s) failed; full results saved to live-ocr-results.json")

if __name__ == "__main__":
    main()
