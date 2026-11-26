"""Bounded PDF-to-DOCX conversion using pdf2docx after password authentication."""
from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

import pymupdf

MAX_CONVERT_PAGES = 20
MAX_OUTPUT_BYTES = 30 * 1024 * 1024


def _apply_arabic_direction(docx_bytes: bytes) -> bytes:
    """Set Word's complex-script RTL metadata only on paragraphs containing Arabic."""
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    document = Document(io.BytesIO(docx_bytes))

    def paragraphs(container):
        for paragraph in getattr(container, "paragraphs", []):
            yield paragraph
        for table in getattr(container, "tables", []):
            for row in table.rows:
                for cell in row.cells:
                    yield from paragraphs(cell)

    for paragraph in paragraphs(document):
        text = paragraph.text or ""
        if not any(0x0600 <= ord(char) <= 0x06ff for char in text):
            continue
        p_pr = paragraph._p.get_or_add_pPr()
        bidi = p_pr.find(qn("w:bidi"))
        if bidi is None:
            bidi = OxmlElement("w:bidi")
            p_pr.append(bidi)
        bidi.set(qn("w:val"), "1")
        for run in paragraph.runs:
            if not any(0x0600 <= ord(char) <= 0x06ff for char in run.text):
                continue
            r_pr = run._r.get_or_add_rPr()
            rtl = r_pr.find(qn("w:rtl"))
            if rtl is None:
                rtl = OxmlElement("w:rtl")
                r_pr.append(rtl)
            rtl.set(qn("w:val"), "1")
            lang = r_pr.find(qn("w:lang"))
            if lang is None:
                lang = OxmlElement("w:lang")
                r_pr.append(lang)
            lang.set(qn("w:val"), "ar-SA")
            lang.set(qn("w:bidi"), "ar-SA")

    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def convert_pdf_to_docx(data: bytes, password: str = "") -> bytes:
    try:
        source = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("الملف ليس PDF صالحًا.") from exc
    try:
        auth = 0
        if source.needs_pass:
            if not password:
                raise ValueError("الملف محمي. أدخل كلمة المرور الصحيحة أولًا.")
            auth = source.authenticate(password)
            if auth <= 0:
                raise ValueError("كلمة مرور الملف غير صحيحة.")
        if not 1 <= source.page_count <= MAX_CONVERT_PAGES:
            raise ValueError(f"التحويل يدعم من صفحة واحدة إلى {MAX_CONVERT_PAGES} صفحة في الطلب الواحد.")
        if source.needs_pass and auth != 4 and not (source.permissions & pymupdf.PDF_PERM_MODIFY):
            raise PermissionError("كلمة المرور لا تسمح بالتعديل؛ يلزم إذن مالك الملف.")
        with tempfile.TemporaryDirectory(prefix="alfalqi-docx-") as temp_dir:
            pdf_path = Path(temp_dir) / "source.pdf"
            docx_path = Path(temp_dir) / "converted.docx"
            source.save(str(pdf_path), encryption=pymupdf.PDF_ENCRYPT_NONE, garbage=4, deflate=True)
            source.close()
            from pdf2docx import Converter
            converter = Converter(str(pdf_path))
            try:
                converter.convert(str(docx_path), start=0, end=None)
            finally:
                converter.close()
            if not docx_path.is_file():
                raise ValueError("لم ينتج محرك التحويل ملف Word.")
            output = _apply_arabic_direction(docx_path.read_bytes())
            if not output or len(output) > MAX_OUTPUT_BYTES:
                raise ValueError("حجم ملف Word الناتج خارج الحد المسموح.")
            if not output.startswith(b"PK"):
                raise ValueError("ملف Word الناتج غير صالح.")
            return output
    finally:
        if not source.is_closed:
            source.close()


def analyze_pdf_docx_quality(pdf_bytes: bytes, docx_bytes: bytes) -> dict:
    """Return bounded, approximate text and structure indicators for a PDF/DOCX pair."""
    import io
    import re
    import unicodedata
    from collections import Counter
    from docx import Document

    report = {
        "analysis_status": "ok",
        "source_word_count": 0,
        "output_word_count": 0,
        "matched_word_count": 0,
        "text_coverage_percent": None,
        "text_precision_percent": None,
        "source_extractable": False,
        "output_paragraph_count": 0,
        "output_table_count": 0,
        "output_image_count": 0,
        "source_image_count": 0,
    }
    try:
        source = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        try:
            if source.needs_pass:
                report["analysis_status"] = "encrypted_source"
                return report
            if not 1 <= source.page_count <= MAX_CONVERT_PAGES:
                report["analysis_status"] = "page_limit_exceeded"
                return report
            source_parts = []
            source_chars = 0
            for page in source:
                page_text = page.get_text("text") or ""
                source_chars += len(page_text)
                if source_chars > 1_500_000:
                    report["analysis_status"] = "source_text_limit_exceeded"
                    return report
                source_parts.append(page_text)
                report["source_image_count"] += len(page.get_images(full=True))
        finally:
            source.close()

        converted = Document(io.BytesIO(docx_bytes))
        output_parts = [paragraph.text for paragraph in converted.paragraphs]
        report["output_paragraph_count"] = len(converted.paragraphs)
        report["output_table_count"] = len(converted.tables)
        report["output_image_count"] = len(converted.inline_shapes)
        for table in converted.tables:
            for row in table.rows:
                for cell in row.cells:
                    output_parts.append(cell.text)

        def tokens(value):
            normalized = unicodedata.normalize("NFKC", value).casefold()
            return re.findall(r"\w+", normalized, flags=re.UNICODE)

        source_tokens = tokens("\n".join(source_parts))
        output_tokens = tokens("\n".join(output_parts))
        report["source_word_count"] = len(source_tokens)
        report["output_word_count"] = len(output_tokens)
        if not source_tokens:
            report["analysis_status"] = "no_extractable_source_text"
            return report
        report["source_extractable"] = True
        overlap = sum((Counter(source_tokens) & Counter(output_tokens)).values())
        report["matched_word_count"] = overlap
        report["text_coverage_percent"] = round(100 * overlap / len(source_tokens), 2)
        if output_tokens:
            report["text_precision_percent"] = round(100 * overlap / len(output_tokens), 2)
        return report
    except Exception:
        report["analysis_status"] = "analysis_unavailable"
        return report
