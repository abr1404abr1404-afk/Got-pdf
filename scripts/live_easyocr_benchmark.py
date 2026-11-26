#!/usr/bin/env python3
"""Evaluate EasyOCR on the same authentic Arabic page and scan used by live OCR tests."""
from __future__ import annotations
import hashlib, json, re, tarfile, tempfile, time, unicodedata
from pathlib import Path
import requests
import numpy as np
import pymupdf
from PIL import Image, ImageOps
import easyocr
import pytesseract

PDF_URL = "https://dlp.dubai.gov.ae/Legislation%20Ar%20Reference/2025/%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%B1%D9%82%D9%85%20(7)%20%D9%84%D8%B3%D9%86%D8%A9%202025%20%D8%A8%D8%B4%D8%A3%D9%86%20%D8%AA%D9%86%D8%B8%D9%8A%D9%85%20%D9%85%D8%B2%D8%A7%D9%88%D9%84%D8%A9%20%D8%A3%D9%86%D8%B4%D8%B7%D8%A9%20%D8%A7%D9%84%D9%85%D9%82%D8%A7%D9%88%D9%84%D8%A7%D8%AA.pdf"
NOD_URL = "https://zenodo.org/api/records/5068735/files/yarmouk_01_col.tar.lzma/content"
NOD_MD5 = "a845e80b66fea3507ad39f3c07684ff6"

def normalize(s):
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", s)
    return re.sub(r"\s+", "", s)

def character_error(reference, candidate):
    a, b = normalize(reference), normalize(candidate)
    if not a: return None
    prev = list(range(len(b) + 1))
    for i, ch in enumerate(a, 1):
        cur = [i]
        for j, other in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (ch != other)))
        prev = cur
    return round(prev[-1] / len(a), 4)

def fetch(url, path):
    response = requests.get(url, timeout=(20, 180), headers={"User-Agent":"GotPDF-EasyOCR-benchmark/1.0"})
    response.raise_for_status()
    path.write_bytes(response.content)
    return response.content

def prepare(pil):
    image = ImageOps.exif_transpose(pil).convert("RGB")
    image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    return image

def run_reader(reader, image):
    started = time.perf_counter()
    results = reader.readtext(np.asarray(image), detail=1, paragraph=False, batch_size=1, workers=0)
    rows = []
    for box, text, confidence in results:
        pts = np.asarray(box, dtype=float).reshape(-1, 2)
        if len(pts) < 4 or not str(text).strip(): continue
        x0, y0 = pts.min(axis=0); x1, y1 = pts.max(axis=0)
        rows.append({"text":str(text).strip(),"confidence":round(float(confidence),4),
                     "bbox":[int(x0),int(y0),int(x1),int(y1)]})
    rows.sort(key=lambda r:(r["bbox"][1]+r["bbox"][3])/2)
    heights=sorted(max(1,r["bbox"][3]-r["bbox"][1]) for r in rows)
    tolerance=max(8, heights[len(heights)//2]*0.65) if heights else 8
    bands=[]; centers=[]
    for row in rows:
        cy=(row["bbox"][1]+row["bbox"][3])/2
        if not bands or abs(cy-centers[-1])>tolerance:
            bands.append([row]); centers.append(cy)
        else:
            bands[-1].append(row)
            centers[-1]=sum((x["bbox"][1]+x["bbox"][3])/2 for x in bands[-1])/len(bands[-1])
    lines=[]
    for band in bands:
        combined=" ".join(x["text"] for x in band)
        ar=sum(0x600<=ord(c)<=0x6ff for c in combined)
        en=sum(c.isascii() and c.isalpha() for c in combined)
        band.sort(key=lambda r:r["bbox"][0],reverse=ar>=en)
        lines.append(" ".join(x["text"] for x in band))
    text="\n".join(lines)
    return {"text":text,"lines":len(lines),"words":len(rows),
            "arabic_chars":sum(0x600<=ord(c)<=0x6ff for c in text),
            "seconds":round(time.perf_counter()-started,2),
            "mean_confidence":round(sum(x["confidence"] for x in rows)/len(rows),4) if rows else 0}


def run_tesseract(image):
    reports = []
    for psm in (11, 6):
        started = time.perf_counter()
        text = pytesseract.image_to_string(image, lang="ara+eng", config=f"--oem 1 --psm {psm}")
        reports.append({
            "psm": psm,
            "text": text,
            "arabic_chars": sum(0x600 <= ord(c) <= 0x6ff for c in text),
            "seconds": round(time.perf_counter() - started, 2),
        })
    return reports

def main():
    report={"engine":"EasyOCR","version":getattr(easyocr,"__version__","unknown"),"tests":[]}
    reader=easyocr.Reader(["ar","en"],gpu=False,verbose=False)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        try:
            pdf=root/"dubai-law.pdf"; fetch(PDF_URL,pdf)
            doc=pymupdf.open(pdf); page=doc[0]
            pix=page.get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False)
            image=Image.frombytes("RGB",[pix.width,pix.height],pix.samples)
            image=prepare(image)
            result=run_reader(reader,image)
            tess = run_tesseract(image)
            for baseline in tess:
                baseline["cer_vs_embedded_pdf_text"] = character_error(page.get_text("text"), baseline["text"])
            result.update({"name":"real_dubai_law_page1","status":"passed",
                           "cer_vs_embedded_pdf_text":character_error(page.get_text("text"),result["text"]),
                           "reference_chars":len(normalize(page.get_text("text"))), "tesseract_baselines":tess})
            report["tests"].append(result); doc.close()
        except Exception as exc:
            report["tests"].append({"name":"real_dubai_law_page1","status":"failed","error":f"{type(exc).__name__}: {str(exc)[:500]}"})
        try:
            archive=root/"nod_scans.tar.lzma"; raw=fetch(NOD_URL,archive)
            if hashlib.md5(raw).hexdigest()!=NOD_MD5: raise ValueError("NOD archive checksum mismatch")
            with tarfile.open(archive,"r:xz") as tar:
                members=[m for m in tar.getmembers() if m.isfile() and Path(m.name).suffix.lower() in {".png",".jpg",".jpeg",".tif",".tiff"}]
                if not members: raise ValueError("No raster scan found")
                member=members[0]; stream=tar.extractfile(member)
                if stream is None: raise ValueError("Could not read scan")
                scan=prepare(Image.open(stream))
            result=run_reader(reader,scan)
            tess = run_tesseract(scan)
            result.update({"name":"real_nod_scanned_page","status":"passed","source_member":member.name,"tesseract_baselines":tess})
            report["tests"].append(result)
        except Exception as exc:
            report["tests"].append({"name":"real_nod_scanned_page","status":"failed","error":f"{type(exc).__name__}: {str(exc)[:500]}"})
    Path("easyocr-live-results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if any(x.get("status")!="passed" for x in report["tests"]): raise SystemExit("One or more EasyOCR real-file tests failed")

if __name__=="__main__": main()
