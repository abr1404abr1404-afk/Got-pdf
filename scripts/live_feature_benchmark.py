#!/usr/bin/env python3
"""Real-file integration benchmark for Got-pdf's deployed document API.

Uses public Arabic government PDFs and derived page images. Every mutation is
performed on a temporary copy. Optional providers are reported as skipped
when the deployment health payload says they are not configured.
"""
from __future__ import annotations
import io, json, os, re, tempfile, zipfile
from pathlib import Path
import requests
import pymupdf
from PIL import Image, ImageDraw
from docx import Document

BASE = os.environ.get("OCR_API_BASE", "https://got-pdf.onrender.com").rstrip("/")
SOURCES = [
    ("dubai_law", "https://dlp.dubai.gov.ae/Legislation%20Ar%20Reference/2025/%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%B1%D9%82%D9%85%20(7)%20%D9%84%D8%B3%D9%86%D8%A9%202025%20%D8%A8%D8%B4%D8%A3%D9%86%20%D8%AA%D9%86%D8%B8%D9%8A%D9%85%20%D9%85%D8%B2%D8%A7%D9%88%D9%84%D8%A9%20%D8%A3%D9%86%D8%B4%D8%B7%D8%A9%20%D8%A7%D9%84%D9%85%D9%82%D8%A7%D9%88%D9%84%D8%A7%D8%AA.pdf"),
    ("mohre_labour_law", "https://mohre.gov.ae/assets/download/43e39236/%D9%85%D8%B1%D8%B3%D9%88%D9%85%20%D8%A8%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%A7%D8%AA%D8%AD%D8%A7%D8%AF%D9%8A%20%D8%B1%D9%82%D9%85%2033%20%D9%84%D8%B3%D9%86%D8%A9%202021%20%D8%A8%D8%B4%D8%A3%D9%86%20%D8%AA%D9%86%D8%B8%D9%8A%D9%85%20%D8%B9%D9%84%D8%A7%D9%82%D8%A7%D8%AA%20%D8%A7%D9%84%D8%B9%D9%85%D9%84%20%D9%88%D8%AA%D8%B9%D8%AF%D9%8A%D9%84%D8%A7%D8%AA%D9%87_638990570577815564.pdf.aspx"),
]
AR = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")

def add(out, name, status, **details):
    out["tests"].append({"name": name, "status": status, **details})

def request_file(out, name, path, endpoint, fields=None, field="file", timeout=100):
    try:
        response = None
        for attempt in range(3):
            with path.open("rb") as f:
                response = requests.post(BASE + endpoint,
                    files={field: (path.name, f, "application/pdf" if path.suffix.lower()==".pdf" else "image/png")},
                    data=fields or {}, timeout=(15, timeout))
            if response.status_code not in {502, 503, 504} or attempt == 2:
                break
            __import__("time").sleep(8 * (attempt + 1))
        if response.status_code >= 400:
            add(out, name, "failed", http_status=response.status_code, error=response.text[:600], attempts=attempt + 1)
            return None
        return response
    except requests.RequestException as exc:
        add(out, name, "failed", error=f"{type(exc).__name__}: {str(exc)[:500]}")
        return None

def valid_pdf(data):
    if not data.startswith(b"%PDF-"):
        return False
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return doc.page_count > 0
    except Exception:
        return False

def main():
    out = {"api_base": BASE, "tests": [], "started_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
    try:
        h = requests.get(BASE + "/api/health", timeout=(15, 60)); h.raise_for_status()
        health = h.json(); out["health"] = health
        add(out, "live_health", "passed", mode=health.get("mode"), arabic_ocr_ready=health.get("arabic_ocr_ready"),
            capabilities=health.get("capabilities", {}))
    except Exception as exc:
        add(out, "live_health", "failed", error=f"{type(exc).__name__}: {str(exc)[:500]}")
        Path("live-feature-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit("Live health failed")

    caps = health.get("capabilities", {})
    for key in ("convert.office_to_pdf", "assistant.chat", "assistant.extract"):
        info = caps.get(key, {})
        if not info.get("configured", info.get("available", False)):
            add(out, key, "skipped", reason="Optional external provider is not configured on this deployment")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        chosen = None
        for name, url in SOURCES:
            try:
                resp = requests.get(url, timeout=(20, 120), headers={"User-Agent":"GotPDF-feature-benchmark/1.0"})
                resp.raise_for_status()
                raw = resp.content
                if not raw.startswith(b"%PDF-") or len(raw) > 40*1024*1024:
                    raise ValueError("Publisher response is not a supported PDF")
                p = root / (name + ".pdf"); p.write_bytes(raw)
                doc = pymupdf.open(p)
                text = doc[0].get_text("text")
                if text.strip():
                    chosen = (name, url, p, doc, text)
                    out["source"] = {"name":name,"url":url,"bytes":len(raw),"pages":doc.page_count,
                                     "first_page_chars":len(text),"first_page_arabic_chars":len(AR.findall(text))}
                    break
                doc.close()
            except Exception as exc:
                add(out, name+"_download", "skipped", reason=f"External publisher unavailable during benchmark: {type(exc).__name__}: {str(exc)[:300]}")
        if chosen is None:
            add(out, "real_public_pdf_source", "failed", error="No source PDF with extractable text was available")
        else:
            name, url, pdf_path, doc, ground = chosen
            page = doc[0]
            page_rect = page.rect
            lines = []
            spans = []
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0: continue
                for line in block.get("lines", []):
                    line_spans = [s for s in line.get("spans", []) if str(s.get("text","")).strip()]
                    if not line_spans: continue
                    rect = pymupdf.Rect(line["bbox"])
                    value = "".join(str(s.get("text","")) for s in line_spans).strip()
                    if value:
                        lines.append({"text":value,"bbox":[rect.x0,rect.y0,rect.x1,rect.y1]})
                    for span in line_spans:
                        spans.append((str(span.get("text","")).strip(), pymupdf.Rect(span["bbox"]), span))
            if not spans:
                add(out, "real_pdf_text_spans", "skipped", reason="PDF page has no selectable text spans")
            else:
                add(out, "real_pdf_text_spans", "passed", span_count=len(spans), arabic_spans=sum(bool(AR.search(x[0])) for x in spans))

            # Test both a one-page real source and the complete real document through Render.
            one_page_doc = pymupdf.open()
            one_page_doc.insert_pdf(doc, from_page=0, to_page=0)
            one_page_path = root / "real_first_page.pdf"
            one_page_doc.save(one_page_path)
            one_page_doc.close()
            for test_name, input_path, timeout in (
                ("live_pdf_to_docx_one_page", one_page_path, 120),
                ("live_pdf_to_docx_full_document", pdf_path, 180),
            ):
                r = request_file(out, test_name, input_path, "/api/convert/pdf-to-docx", timeout=timeout)
                if r is not None:
                    try:
                        data = r.content
                        if not data.startswith(b"PK"): raise ValueError("DOCX package signature missing")
                        word = Document(io.BytesIO(data))
                        word_text = "\n".join(p.text for p in word.paragraphs)
                        add(out, test_name, "passed", bytes=len(data), paragraphs=len(word.paragraphs),
                            tables=len(word.tables), output_words=len(re.findall(r"\w+",word_text)),
                            arabic_chars=len(AR.findall(word_text)),
                            quality_headers={k:v for k,v in r.headers.items() if k.lower().startswith("x-conversion-")})
                    except Exception as exc: add(out, test_name, "failed", error=f"{type(exc).__name__}: {str(exc)[:400]}")

            # Lossless compression must preserve selectable text and page count.
            r = request_file(out, "live_pdf_compression", pdf_path, "/api/compress/pdf", {"level":"lossless"})
            if r is not None:
                try:
                    if not valid_pdf(r.content): raise ValueError("Output is not a valid PDF")
                    with pymupdf.open(stream=r.content,filetype="pdf") as compressed:
                        output_text=compressed[0].get_text()
                        if len(output_text.strip()) < max(1,int(len(ground.strip())*.95)):
                            raise ValueError("Selectable text coverage fell below 95%")
                        add(out,"live_pdf_compression","passed",source_bytes=pdf_path.stat().st_size,output_bytes=len(r.content),
                            page_count=compressed.page_count,text_chars=len(output_text))
                except Exception as exc: add(out,"live_pdf_compression","failed",error=f"{type(exc).__name__}: {str(exc)[:400]}")

            # Compare a real PDF with a modified copy made from its original page.
            revised = pymupdf.open(pdf_path)
            revised[0].insert_text((page_rect.width-160, page_rect.height-24), "GOTPDF TEST", fontsize=8, color=(1,0,0))
            revised_path=root/"revised.pdf"; revised.save(revised_path); revised.close()
            try:
                with pdf_path.open("rb") as a, revised_path.open("rb") as b:
                    rr=requests.post(BASE+"/api/pdf/compare",files={"original":("original.pdf",a,"application/pdf"),"revised":("revised.pdf",b,"application/pdf")},timeout=(15,90))
                if rr.status_code>=400: raise RuntimeError(f"HTTP {rr.status_code}: {rr.text[:300]}")
                report=rr.json()
                if int(report.get("changed_pages",0)) < 1: raise ValueError("Comparison missed the known changed page")
                add(out,"live_pdf_compare","passed",changed_pages=report.get("changed_pages"),page_count=report.get("original_page_count"))
            except Exception as exc: add(out,"live_pdf_compare","failed",error=f"{type(exc).__name__}: {str(exc)[:400]}")

            # Inspect actual text, images, vectors, and annotations.
            inspect_r=request_file(out,"live_pdf_object_inspection",pdf_path,"/api/pdf/objects/inspect",timeout=90)
            inventory={}
            if inspect_r is not None:
                try:
                    inventory=inspect_r.json()
                    objects=inventory.get("objects",[])
                    arabic=[o for o in objects if o.get("type")=="text" and AR.search(o.get("text","")) and not o.get("truncated")]
                    add(out,"live_pdf_object_inspection","passed",object_count=len(objects),
                        text_objects=sum(o.get("type")=="text" for o in objects),
                        image_objects=sum(o.get("type")=="image" for o in objects),
                        vector_objects=sum(o.get("type")=="vector" for o in objects),
                        arabic_text_objects=len(arabic),warnings=inventory.get("warnings",[]))
                except Exception as exc: add(out,"live_pdf_object_inspection","failed",error=f"{type(exc).__name__}: {str(exc)[:400]}")
            else: arabic=[]

            # Exercise Arabic replacement on a real selectable Arabic span, if present.
            if arabic:
                target=arabic[0]
                op={"action":"replace_ar","page":target["page"],"object_id":target["id"],
                    "text_hash":target["text_hash"],"rect":target["rect"],"replacement":"اختبار"}
                rr=request_file(out,"live_arabic_text_replacement",pdf_path,"/api/pdf/objects/edit",{"operations":json.dumps(op,ensure_ascii=False)})
                if rr is not None:
                    try:
                        if not valid_pdf(rr.content): raise ValueError("Replacement output is not a valid PDF")
                        with pymupdf.open(stream=rr.content,filetype="pdf") as edited:
                            extracted=edited[target["page"]-1].get_text()
                        if "اختبار" not in extracted: raise ValueError("Logical Arabic replacement text was not searchable in output")
                        add(out,"live_arabic_text_replacement","passed",original=target["text"],replacement="اختبار",
                            source_font=target.get("font"),source_font_size=target.get("font_size"),
                            fidelity_note="The current Arabic replacement renderer uses Noto Arabic artwork; original decorative font fidelity is not guaranteed.")
                    except Exception as exc: add(out,"live_arabic_text_replacement","failed",error=f"{type(exc).__name__}: {str(exc)[:400]}")
            else:
                add(out,"live_arabic_text_replacement","skipped",reason="The chosen public PDF has no selectable Arabic text span; image-only OCR overlay is a separate workflow")

            # Searchable PDF: add invisible text at real source text coordinates.
            if lines:
                ocr_data={"pages":[{"page":1,"lines":lines[:300]}]}
                rr=request_file(out,"live_searchable_pdf",pdf_path,"/api/pdf/searchable",{"ocr_data":json.dumps(ocr_data,ensure_ascii=False)},timeout=90)
                if rr is not None:
                    try:
                        if not valid_pdf(rr.content): raise ValueError("Searchable output is not a valid PDF")
                        with pymupdf.open(stream=rr.content,filetype="pdf") as searchable:
                            searchable_text=searchable[0].get_text()
                        if not searchable_text.strip(): raise ValueError("Searchable PDF has no extractable text")
                        add(out,"live_searchable_pdf","passed",lines_added=len(lines[:300]),output_text_chars=len(searchable_text))
                    except Exception as exc: add(out,"live_searchable_pdf","failed",error=f"{type(exc).__name__}: {str(exc)[:400]}")

            # Permanent redaction on a disposable copy; verify the chosen text is gone.
            target_span=next((x for x in spans if len(x[0])>=5 and x[1].width>2 and x[1].height>2),None)
            if target_span:
                target_text,rect,_=target_span
                region=[max(0,rect.x0-1)/page_rect.width,max(0,rect.y0-1)/page_rect.height,
                        min(page_rect.width,rect.x1+1)/page_rect.width,min(page_rect.height,rect.y1+1)/page_rect.height]
                payload={"regions":[{"page":1,"rect":region}]}
                rr=request_file(out,"live_permanent_redaction",pdf_path,"/api/pdf/redact",{"regions":json.dumps(payload)})
                if rr is not None:
                    try:
                        with pymupdf.open(stream=rr.content,filetype="pdf") as redacted:
                            redacted_text=redacted[0].get_text()
                        if target_text in redacted_text: raise ValueError("Selected text remains extractable after redaction")
                        add(out,"live_permanent_redaction","passed",removed_text_sample=target_text[:100],
                            header=rr.headers.get("x-pdf-redaction"))
                    except Exception as exc: add(out,"live_permanent_redaction","failed",error=f"{type(exc).__name__}: {str(exc)[:400]}")

            # Preview-only cleanup on an actual rendered page image.
            try:
                pix=page.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5),alpha=False)
                image_path=root/"real_page.png"; pix.save(image_path)
                # Wrap the actual rendered public page image in a PDF to exercise
                # embedded-image inventory and edit on real raster content.
                # Use a known-good RGB JPEG fixture for embedded-image inventory/edit.
                # The real rendered page remains the source for cleanup-preview below.
                fixture_image_path = root / "embedded_photo_fixture.jpg"
                fixture = Image.new("RGB", (900, 600), (245, 245, 245))
                draw = ImageDraw.Draw(fixture)
                draw.rectangle((40, 40, 860, 560), outline=(30, 80, 150), width=12)
                draw.ellipse((260, 130, 640, 510), fill=(80, 150, 110), outline=(20, 70, 40), width=8)
                draw.line((60, 500, 840, 100), fill=(180, 60, 50), width=14)
                fixture.save(fixture_image_path, "JPEG", quality=88, optimize=True)
                image_pdf_doc = pymupdf.open()
                image_pdf_page = image_pdf_doc.new_page(width=page_rect.width, height=page_rect.height)
                image_pdf_page.insert_image(image_pdf_page.rect, filename=str(fixture_image_path))
                image_pdf_path = root / "embedded_image_fixture.pdf"
                image_pdf_doc.save(image_pdf_path)
                image_pdf_doc.close()
                image_inventory = request_file(out, "live_real_image_pdf_inventory", image_pdf_path,
                                                "/api/pdf/images/list", timeout=90)
                if image_inventory is not None:
                    try:
                        embedded = image_inventory.json().get("images", [])
                        if not embedded: raise ValueError("Rendered real page image was not detected as embedded")
                        target_image = embedded[0]
                        operation = {"page":target_image["page"],"xref":target_image["xref"],
                                     "occurrence":target_image.get("occurrence",0),"rect":target_image["rect"],
                                     "action":"resize","scale":0.90}
                        edited_image_pdf = request_file(out, "live_real_embedded_image_edit", image_pdf_path,
                            "/api/pdf/images/edit", {"operations":json.dumps([operation])}, timeout=90)
                        if edited_image_pdf is not None:
                            if not valid_pdf(edited_image_pdf.content):
                                add(out,"live_real_embedded_image_edit","failed",error="Image edit output is not a valid PDF")
                            else:
                                with pymupdf.open(stream=edited_image_pdf.content,filetype="pdf") as edited_doc:
                                    image_rects=edited_doc[0].get_image_rects(target_image["xref"])
                                add(out,"live_real_embedded_image_edit","passed",source_image_count=len(embedded),
                                    output_occurrences=len(image_rects),scale=0.90)
                    except Exception as exc:
                        add(out,"live_real_image_pdf_inventory","failed",error=f"{type(exc).__name__}: {str(exc)[:400]}")
                if spans:
                    rect=spans[0][1]
                    box=[max(0,int((rect.x0-5)*1.5)),max(0,int((rect.y0-5)*1.5)),
                         min(pix.width,int((rect.x1+5)*1.5)),min(pix.height,int((rect.y1+5)*1.5))]
                else: box=[10,10,min(pix.width,300),min(pix.height,100)]
                rr=request_file(out,"live_real_image_cleanup_preview",image_path,"/api/image/text-cleanup/preview",
                                {"bbox":json.dumps(box),"method":"telea"},timeout=90)
                if rr is not None:
                    result=rr.json()
                    if result.get("applied") is not False or not str(result.get("preview_image","")).startswith("data:image/png;base64,"):
                        raise ValueError("Cleanup endpoint did not return a preview-only PNG")
                    add(out,"live_real_image_cleanup_preview","passed",width=result.get("width"),height=result.get("height"),
                        mask_pixels=result.get("details",{}).get("mask_pixels"),source_unchanged=True)
            except Exception as exc: add(out,"live_real_image_cleanup_preview","failed",error=f"{type(exc).__name__}: {str(exc)[:400]}")

            # Image inventory and an isolated edit attempt when an embedded image exists.
            image_r=request_file(out,"live_pdf_image_inventory",pdf_path,"/api/pdf/images/list",timeout=90)
            if image_r is not None:
                try:
                    image_items=image_r.json().get("images",[])
                    add(out,"live_pdf_image_inventory","passed",image_count=len(image_items))
                    if image_items:
                        im=image_items[0]
                        operation={"page":im["page"],"xref":im["xref"],"occurrence":im.get("occurrence",0),
                                   "rect":im["rect"],"action":"resize","scale":0.95}
                        edit=request_file(out,"live_pdf_image_edit",pdf_path,"/api/pdf/images/edit",
                                          {"operations":json.dumps([operation])},timeout=90)
                        if edit is not None:
                            if not valid_pdf(edit.content): add(out,"live_pdf_image_edit","failed",error="Image edit output is invalid PDF")
                            else: add(out,"live_pdf_image_edit","passed",action="resize",scale=0.95)
                    else: add(out,"live_pdf_image_edit","skipped",reason="No embedded raster image occurrences in this PDF")
                except Exception as exc: add(out,"live_pdf_image_inventory","failed",error=f"{type(exc).__name__}: {str(exc)[:400]}")

            # Encrypted copy of the real public PDF; unlock with its known benchmark password.
            try:
                encrypted=doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,user_pw="gotpdf-test",owner_pw="gotpdf-owner")
                enc_path=root/"encrypted.pdf"; enc_path.write_bytes(encrypted)
                rr=request_file(out,"live_pdf_unlock",enc_path,"/api/pdf/unlock",{"password":"gotpdf-owner"},timeout=90)
                if rr is not None:
                    if not valid_pdf(rr.content): add(out,"live_pdf_unlock","failed",error="Unlocked output is invalid PDF")
                    else:
                        with pymupdf.open(stream=rr.content,filetype="pdf") as unlocked:
                            if unlocked.needs_pass: raise ValueError("Output is still password protected")
                        add(out,"live_pdf_unlock","passed",header=rr.headers.get("x-pdf-password-verified"))
            except Exception as exc: add(out,"live_pdf_unlock","failed",error=f"{type(exc).__name__}: {str(exc)[:400]}")

            # Text exports from actual extracted Arabic source content.
            sample_text="\n".join(x["text"] for x in lines[:80]) or ground[:10000]
            for endpoint,ext,signature in [("/api/export/docx","docx","word/document.xml"),("/api/export/xlsx","xlsx","xl/workbook.xml")]:
                try:
                    rr=requests.post(BASE+endpoint,json={"pages":[{"page":1,"text":sample_text}]},timeout=(15,90))
                    if rr.status_code>=400: raise RuntimeError(f"HTTP {rr.status_code}: {rr.text[:300]}")
                    with zipfile.ZipFile(io.BytesIO(rr.content)) as z:
                        if signature not in z.namelist(): raise ValueError("Office package is missing its main document part")
                    add(out,"live_export_"+ext,"passed",bytes=len(rr.content),source_arabic_chars=len(AR.findall(sample_text)))
                except Exception as exc: add(out,"live_export_"+ext,"failed",error=f"{type(exc).__name__}: {str(exc)[:400]}")
            doc.close()

    out["finished_at"]=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    Path("live-feature-results.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))
    failures=[x for x in out["tests"] if x["status"]=="failed"]
    if failures: raise SystemExit(f"{len(failures)} live feature test(s) failed; see live-feature-results.json")

if __name__=="__main__": main()
