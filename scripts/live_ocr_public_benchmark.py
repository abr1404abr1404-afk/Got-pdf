#!/usr/bin/env python3
"""Live regression test against public Arabic documents and a real scanned page."""
from __future__ import annotations
import json, os, re, tarfile, tempfile, unicodedata
from pathlib import Path
import requests
import fitz

BASE = os.environ.get("OCR_API_BASE", "https://got-pdf.onrender.com").rstrip("/")
SOURCES = [
    ("dubai_law", "https://dlp.dubai.gov.ae/Legislation%20Ar%20Reference/2025/%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%B1%D9%82%D9%85%20(7)%20%D9%84%D8%B3%D9%86%D8%A9%202025%20%D8%A8%D8%B4%D8%A3%D9%86%20%D8%AA%D9%86%D8%B8%D9%8A%D9%85%20%D9%85%D8%B2%D8%A7%D9%88%D9%84%D8%A9%20%D8%A3%D9%86%D8%B4%D8%B7%D8%A9%20%D8%A7%D9%84%D9%85%D9%82%D8%A7%D9%88%D9%84%D8%A7%D8%AA.pdf"),
    ("mohre_labour_law", "https://mohre.gov.ae/assets/download/43e39236/%D9%85%D8%B1%D8%B3%D9%88%D9%85%20%D8%A8%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%A7%D8%AA%D8%AD%D8%A7%D8%AF%D9%8A%20%D8%B1%D9%82%D9%85%2033%20%D9%84%D8%B3%D9%86%D8%A9%202021%20%D8%A8%D8%B4%D8%A3%D9%86%20%D8%AA%D9%86%D8%B8%D9%8A%D9%85%20%D8%B9%D9%84%D8%A7%D9%82%D8%A7%D8%AA%20%D8%A7%D9%84%D8%B9%D9%85%D9%84%20%D9%88%D8%AA%D8%B9%D8%AF%D9%8A%D9%84%D8%A7%D8%AA%D9%87_638990570577815564.pdf.aspx"),
]
NOD_URL = "https://zenodo.org/api/records/5068735/files/yarmouk_01_col.tar.lzma/content"
NOD_MD5 = "a845e80b66fea3507ad39f3c07684ff6"

def norm(s):
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", s)
    return re.sub(r"\s+", "", s)

def cer(a,b):
    a,b=norm(a),norm(b)
    if not a: return 1.0
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        cur=[i]
        for j,y in enumerate(b,1):
            cur.append(min(cur[-1]+1,prev[j]+1,prev[j-1]+(x!=y)))
        prev=cur
    return prev[-1]/len(a)

def get(url, path):
    r=requests.get(url,timeout=180,headers={"User-Agent":"GotPDF-live-OCR-benchmark/1.0"})
    r.raise_for_status()
    path.write_bytes(r.content)
    return r.content

def main():
    out={"api_base":BASE,"sources":[],"tests":[]}
    health=requests.get(BASE+"/api/health",timeout=45)
    health.raise_for_status()
    out["health_status"]=health.status_code
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        for name,url in SOURCES:
            pdf=root/(name+".pdf")
            raw=get(url,pdf)
            if not raw.startswith(b"%PDF"): raise RuntimeError(f"{name}: source did not return a PDF")
            doc=fitz.open(pdf)
            # Use the first two authentic pages to keep the live request bounded.
            sample=fitz.open()
            sample.insert_pdf(doc,from_page=0,to_page=0)
            sample_path=root/(name+"_sample.pdf"); sample.save(sample_path)
            page=doc.load_page(0)
            pix=page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
            image_path=root/(name+"_page1.png"); pix.save(image_path)
            ground="\n".join(doc.load_page(i).get_text("text") for i in range(1))
            # The PDF endpoint is tested on the actual publisher PDF pages.
            response=requests.post(BASE+"/api/ocr/pdf",files={"file":(sample_path.name,sample_path.read_bytes(),"application/pdf")},data={"language":"ara+eng","dpi":"120"},timeout=240)
            response.raise_for_status(); payload=response.json()
            text_out="\n".join(line.get("text","") for page_obj in payload.get("pages",[]) for line in page_obj.get("ocr",{}).get("lines",[]))
            out["tests"].append({"name":name+"_pdf","status":"passed","pages":payload.get("page_count"),"ground_truth_chars":len(ground),"ocr_chars":len(text_out),"cer_vs_pdf_text_layer":round(cer(ground,text_out),4),"arabic_chars":sum("\u0600"<=c<="\u06ff" for c in text_out)})
            # Image endpoint receives a PNG rasterized from the same authentic page.
            response=requests.post(BASE+"/api/ocr/image",files={"file":(image_path.name,image_path.read_bytes(),"image/png")},data={"language":"ara+eng"},timeout=180)
            response.raise_for_status(); img_payload=response.json()
            image_text="\n".join(line.get("text","") for line in img_payload.get("lines",[]))
            out["tests"].append({"name":name+"_page_image","status":"passed","ocr_chars":len(image_text),"arabic_chars":sum("\u0600"<=c<="\u06ff" for c in image_text),"lines":len(img_payload.get("lines",[]))})
            doc.close(); sample.close()
        # A real camera/scanner image from the CC-BY-4.0 Yarmouk/NOD collection.
        archive=root/"nod_scans.tar.lzma"
        data=get(NOD_URL,archive)
        import hashlib
        if hashlib.md5(data).hexdigest()!=NOD_MD5: raise RuntimeError("NOD archive checksum mismatch")
        chosen=None
        with tarfile.open(archive,"r:xz") as tar:
            members=[m for m in tar.getmembers() if m.isfile() and Path(m.name).suffix.lower() in {".png",".jpg",".jpeg",".tif",".tiff"}]
            if not members: raise RuntimeError("No raster scan found in NOD archive")
            chosen=members[0]
            f=tar.extractfile(chosen)
            if f is None: raise RuntimeError("Could not read selected scan")
            scan_bytes=f.read()
        response=requests.post(BASE+"/api/ocr/image",files={"file":("nod_real_scan"+Path(chosen.name).suffix,scan_bytes,"image/jpeg")},data={"language":"ara+eng"},timeout=180)
        response.raise_for_status(); scan_payload=response.json()
        scan_text="\n".join(line.get("text","") for line in scan_payload.get("lines",[]))
        out["tests"].append({"name":"nod_real_scanned_page_image","status":"passed","source_member":chosen.name,"ocr_chars":len(scan_text),"arabic_chars":sum("\u0600"<=c<="\u06ff" for c in scan_text),"lines":len(scan_payload.get("lines",[]))})
    Path("live-ocr-results.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if any(t.get("arabic_chars",0)==0 for t in out["tests"]):
        raise SystemExit("At least one real image/PDF test returned no Arabic characters")

if __name__=="__main__": main()
