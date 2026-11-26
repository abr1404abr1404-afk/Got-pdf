#!/usr/bin/env python3
"""Evaluate Surya line-level Arabic OCR on the same public PDF page and real scan."""
from __future__ import annotations
import hashlib, json, re, subprocess, tarfile, tempfile, time, unicodedata
from pathlib import Path
import requests
import pymupdf
from PIL import Image, ImageOps

PDF_URL = "https://dlp.dubai.gov.ae/Legislation%20Ar%20Reference/2025/%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%B1%D9%82%D9%85%20(7)%20%D9%84%D8%B3%D9%86%D8%A9%202025%20%D8%A8%D8%B4%D8%A3%D9%86%20%D8%AA%D9%86%D8%B8%D9%8A%D9%85%20%D9%85%D8%B2%D8%A7%D9%88%D9%84%D8%A9%20%D8%A3%D9%86%D8%B4%D8%B7%D8%A9%20%D8%A7%D9%84%D9%85%D9%82%D8%A7%D9%88%D9%84%D8%A7%D8%AA.pdf"
NOD_URL = "https://zenodo.org/api/records/5068735/files/yarmouk_01_col.tar.lzma/content"
NOD_MD5 = "a845e80b66fea3507ad39f3c07684ff6"

def normalize(s):
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", s)
    return re.sub(r"\s+", "", s)

def cer(reference, candidate):
    a,b=normalize(reference),normalize(candidate)
    if not a: return None
    prev=list(range(len(b)+1))
    for i,ch in enumerate(a,1):
        cur=[i]
        for j,other in enumerate(b,1):
            cur.append(min(cur[-1]+1,prev[j]+1,prev[j-1]+(ch!=other)))
        prev=cur
    return round(prev[-1]/len(a),4)

def fetch(url,path):
    response=requests.get(url,timeout=(20,180),headers={"User-Agent":"GotPDF-Surya-benchmark/1.0"})
    response.raise_for_status()
    path.write_bytes(response.content)
    return response.content

def prepare(image):
    image=ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((1600,1600),Image.Resampling.LANCZOS)
    return image

def extract_lines(page):
    rows=page.get("text_lines") or []
    if not rows and page.get("blocks"):
        for block in page["blocks"]:
            text=block.get("text") or block.get("html") or ""
            if text:
                rows.append({"text":re.sub(r"<[^>]+>"," ",str(text)),"bbox":block.get("bbox",[0,0,0,0])})
    cleaned=[]
    for row in rows:
        text=str(row.get("text","")).strip()
        if not text: continue
        box=row.get("bbox") or [0,0,0,0]
        cleaned.append({"text":text,"bbox":box})
    cleaned.sort(key=lambda x: ((x["bbox"][1]+x["bbox"][3])/2 if len(x["bbox"])==4 else 0))
    ordered=[]
    for row in cleaned:
        box=row["bbox"]
        center=(box[1]+box[3])/2 if len(box)==4 else 0
        if not ordered or abs(center-ordered[-1]["center"])>14:
            ordered.append({"center":center,"rows":[row]})
        else:
            ordered[-1]["rows"].append(row)
            ordered[-1]["center"]=sum(((x["bbox"][1]+x["bbox"][3])/2 if len(x["bbox"])==4 else 0) for x in ordered[-1]["rows"])/len(ordered[-1]["rows"])
    lines=[]
    for band in ordered:
        items=band["rows"]
        text=" ".join(x["text"] for x in items)
        ar=sum(0x600<=ord(c)<=0x6ff for c in text)
        en=sum(c.isascii() and c.isalpha() for c in text)
        items.sort(key=lambda x:x["bbox"][0] if len(x["bbox"])==4 else 0,reverse=ar>=en)
        lines.append(" ".join(x["text"] for x in items))
    return lines

def main():
    report={"engine":"Surya OCR","tests":[]}
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp); inputs=root/"inputs"; outputs=root/"outputs"
        inputs.mkdir(); outputs.mkdir()
        cases={}
        try:
            pdf=root/"dubai-law.pdf"; fetch(PDF_URL,pdf)
            doc=pymupdf.open(pdf); page=doc[0]
            pix=page.get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False)
            page_image=prepare(Image.frombytes("RGB",[pix.width,pix.height],pix.samples))
            page_path=inputs/"dubai_law_page1.png"; page_image.save(page_path)
            cases["dubai_law_page1"]={"reference":page.get_text("text")}
            doc.close()
        except Exception as exc:
            report["tests"].append({"name":"real_dubai_law_page1","status":"failed","error":f"{type(exc).__name__}: {str(exc)[:400]}"})
        try:
            archive=root/"nod_scans.tar.lzma"; raw=fetch(NOD_URL,archive)
            if hashlib.md5(raw).hexdigest()!=NOD_MD5: raise ValueError("NOD archive checksum mismatch")
            with tarfile.open(archive,"r:xz") as tar:
                members=[m for m in tar.getmembers() if m.isfile() and Path(m.name).suffix.lower() in {".png",".jpg",".jpeg",".tif",".tiff"}]
                if not members: raise ValueError("No scan found")
                member=members[0]; stream=tar.extractfile(member)
                if stream is None: raise ValueError("Could not read scan")
                scan=prepare(Image.open(stream))
            scan_path=inputs/"nod_real_scan.png"; scan.save(scan_path)
            cases["nod_real_scan"]={"source_member":member.name}
        except Exception as exc:
            report["tests"].append({"name":"real_nod_scanned_page","status":"failed","error":f"{type(exc).__name__}: {str(exc)[:400]}"})
        if cases:
            started=time.perf_counter()
            try:
                proc=subprocess.run(["surya_ocr",str(inputs),"--output_dir",str(outputs)],
                    capture_output=True,text=True,timeout=1200,check=False)
                report["runtime_seconds"]=round(time.perf_counter()-started,2)
                if proc.returncode!=0:
                    raise RuntimeError((proc.stderr or proc.stdout or "Surya command failed")[-1800:])
                result_file=outputs/"results.json"
                if not result_file.exists():
                    matches=list(outputs.rglob("results.json"))
                    if not matches: raise FileNotFoundError("Surya results.json was not created")
                    result_file=matches[0]
                result=json.loads(result_file.read_text(encoding="utf-8"))
                for key,meta in cases.items():
                    pages=result.get(key) or result.get(key+".png") or []
                    if isinstance(pages,dict): pages=[pages]
                    page=pages[0] if pages else {}
                    lines=extract_lines(page)
                    text="\n".join(lines)
                    item={"name":key,"status":"passed" if text else "failed","lines":len(lines),
                          "chars":len(text),"arabic_chars":sum(0x600<=ord(c)<=0x6ff for c in text),
                          "text":text[:12000],"seconds":round(report["runtime_seconds"]/max(1,len(cases)),2)}
                    if "reference" in meta:
                        item["cer_vs_embedded_pdf_text"]=cer(meta["reference"],text)
                    if "source_member" in meta: item["source_member"]=meta["source_member"]
                    if not text: item["error"]="Surya returned no text lines"
                    report["tests"].append(item)
            except Exception as exc:
                report["runtime_seconds"]=round(time.perf_counter()-started,2)
                report["error"]=f"{type(exc).__name__}: {str(exc)[:1800]}"
                for key in cases:
                    report["tests"].append({"name":key,"status":"failed","error":report["error"]})
    Path("surya-live-results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if any(x.get("status")=="failed" for x in report["tests"]):
        raise SystemExit("One or more Surya real-file tests failed; report saved")

if __name__=="__main__": main()
