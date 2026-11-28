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


def _append_ocr_word_table(document, table_data: dict, direction: str):
    """Append a bounded, editable table reconstructed from OCR cell rows."""
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    rows = table_data.get("rows")
    if not isinstance(rows, list):
        return None
    clean = []
    columns = 0
    for row in rows[:60]:
        if isinstance(row, (list, tuple)):
            values = [str(value or "").strip()[:4000] for value in row[:20]]
            if values:
                clean.append(values)
                columns = max(columns, len(values))
    if not clean or not columns:
        return None
    table = document.add_table(rows=len(clean), cols=columns)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    table_pr = table._tbl.tblPr
    bidi = table_pr.find(qn("w:bidiVisual"))
    if bidi is None:
        bidi = OxmlElement("w:bidiVisual")
        table_pr.append(bidi)
    bidi.set(qn("w:val"), "1" if direction == "rtl" else "0")
    for row_index, values in enumerate(clean):
        for column_index in range(columns):
            cell = table.cell(row_index, column_index)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cell.text = values[column_index] if column_index < len(values) else ""
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT if direction == "rtl" else WD_ALIGN_PARAGRAPH.LEFT
                if direction == "rtl":
                    p_pr = paragraph._p.get_or_add_pPr()
                    p_bidi = OxmlElement("w:bidi")
                    p_bidi.set(qn("w:val"), "1")
                    p_pr.append(p_bidi)
                paragraph.paragraph_format.space_before = 0
                paragraph.paragraph_format.space_after = 0
                for run in paragraph.runs:
                    run.font.name = "Arial"
                    if any(0x0600 <= ord(char) <= 0x06ff for char in run.text):
                        r_pr = run._element.get_or_add_rPr()
                        rtl = OxmlElement("w:rtl")
                        rtl.set(qn("w:val"), "1")
                        r_pr.append(rtl)
    return table


def create_ocr_docx(pages: list[dict]) -> bytes:
    """Rebuild editable Word paragraphs from OCR lines while retaining RTL, size and spacing cues."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    if not pages or len(pages) > 20:
        raise ValueError("عدد صفحات OCR للتحويل غير صالح.")
    total_chars = sum(
        len(str(line.get("text", "")))
        for page in pages for line in (page.get("lines") or [])
    )
    if total_chars < 1 or total_chars > 200_000:
        raise ValueError("النص المستخرج غير كافٍ أو يتجاوز حد التحويل.")

    document = Document()
    document.core_properties.title = "مستند مستخرج ضوئيًا - الفلقي PDF"
    document.core_properties.author = "الفلقي PDF"
    for page_index, page in enumerate(pages):
        if page_index:
            document.add_page_break()
        # Match the source PDF's physical page size when geometry is available.
        # This avoids silently rebuilding A4/legal pages on Word's default Letter canvas.
        section = document.sections[-1]
        try:
            page_width_pt = float(page.get("page_width_pt", 0) or 0)
            page_height_pt = float(page.get("page_height_pt", 0) or 0)
            if 100 <= page_width_pt <= 2000 and 100 <= page_height_pt <= 3000:
                section.page_width = Pt(page_width_pt)
                section.page_height = Pt(page_height_pt)
                section.top_margin = Pt(0)
                section.bottom_margin = Pt(0)
                section.left_margin = Pt(0)
                section.right_margin = Pt(0)
                section.header_distance = Pt(0)
                section.footer_distance = Pt(0)
        except (TypeError, ValueError, OverflowError):
            pass
        dpi = max(72, int(page.get("dpi", 180)))
        # OCR preprocessing may resize pages to a bounded working canvas. Use
        # the actual analyzed image dimensions when available; DPI alone would
        # shift every line on resized scans.
        try:
            image_width = float(page.get("image_width", 0) or 0)
            image_height = float(page.get("image_height", 0) or 0)
            page_width_pt = float(section.page_width.pt)
            page_height_pt = float(section.page_height.pt)
            points_per_pixel_x = page_width_pt / image_width if image_width > 0 else 72.0 / dpi
            points_per_pixel_y = page_height_pt / image_height if image_height > 0 else 72.0 / dpi
        except (TypeError, ValueError, ZeroDivisionError):
            points_per_pixel_x = points_per_pixel_y = 72.0 / dpi
        direction = page.get("direction", "rtl")
        table_regions = []
        for table_data in (page.get("tables") or []):
            if not isinstance(table_data, dict):
                continue
            box = table_data.get("bbox")
            if isinstance(box, (list, tuple)) and len(box) == 4 and isinstance(table_data.get("rows"), list):
                try:
                    x0, y0, x1, y1 = (float(value) for value in box)
                    if x1 > x0 and y1 > y0:
                        table_regions.append((x0, y0, x1, y1, table_data))
                except (TypeError, ValueError):
                    pass
        lines = []
        for line in (page.get("lines") or []):
            if not str(line.get("text", "")).strip():
                continue
            box = line.get("bbox") or []
            try:
                cx, cy = (float(box[0]) + float(box[2])) / 2, (float(box[1]) + float(box[3])) / 2
            except (TypeError, ValueError, IndexError):
                cx = cy = -1
            if any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1, _ in table_regions):
                continue
            lines.append(line)
        paragraph_positions = []
        # Layout analysis assigns columns in reading order; within each column,
        # preserve top-to-bottom placement and use OCR boxes to approximate spacing.
        if any(line.get("reading_order") is not None for line in lines):
            def reading_key(line):
                try:
                    rank = int(line.get("reading_order"))
                except (TypeError, ValueError):
                    rank = 0
                if rank > 0:
                    return (0, rank, 0.0, 0.0)
                box = line.get("bbox") or [0, 0, 0, 0]
                try:
                    x0, y0 = float(box[0]), float(box[1])
                except (TypeError, ValueError, IndexError):
                    x0, y0 = 0.0, 0.0
                x_key = -x0 if direction == "rtl" else x0
                return (1, int(line.get("column", 1)), y0, x_key)
            lines.sort(key=reading_key)
        else:
            lines.sort(key=lambda line: (
                int(line.get("column", 1)),
                float((line.get("bbox") or [0, 0, 0, 0])[1]),
                -float((line.get("bbox") or [0, 0, 0, 0])[0]) if direction == "rtl" else float((line.get("bbox") or [0, 0, 0, 0])[0]),
            ))
        previous_bottom = 0.0
        for line in lines:
            text = str(line.get("text", "")).strip()
            box = line.get("bbox") or [0, 0, 0, 0]
            try:
                y0, y1 = float(box[1]), float(box[3])
            except (TypeError, ValueError, IndexError):
                y0, y1 = previous_bottom, previous_bottom + 16
            gap_pt = max(0.0, min(36.0, (y0 - previous_bottom) * points_per_pixel_y * 0.45))
            height_pt = max(6.0, min(48.0, (y1 - y0) * points_per_pixel_y * 0.82))
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT if direction == "rtl" else WD_ALIGN_PARAGRAPH.LEFT
            paragraph.paragraph_format.space_before = Pt(gap_pt)
            paragraph.paragraph_format.space_after = Pt(1.5)
            paragraph.paragraph_format.line_spacing = 1.0
            # Preserve horizontal placement as paragraph indents. This is more
            # stable in Word/LibreOffice than relying on right alignment alone.
            if page.get("preserve_positioning", True):
                try:
                    page_width_pt = float(section.page_width.pt)
                    x0, x1 = float(box[0]), float(box[2])
                    left_gap = max(0.0, min(page_width_pt, x0 * points_per_pixel_x))
                    right_gap = max(0.0, min(page_width_pt, page_width_pt - x1 * points_per_pixel_x))
                    if left_gap + right_gap > page_width_pt - 8:
                        factor = max(0.0, (page_width_pt - 8) / max(1.0, left_gap + right_gap))
                        left_gap *= factor
                        right_gap *= factor
                    paragraph.paragraph_format.left_indent = Pt(left_gap)
                    paragraph.paragraph_format.right_indent = Pt(right_gap)
                except (TypeError, ValueError, IndexError):
                    pass
            if direction == "rtl":
                p_pr = paragraph._p.get_or_add_pPr()
                bidi = OxmlElement("w:bidi")
                bidi.set(qn("w:val"), "1")
                p_pr.append(bidi)
            paragraph_positions.append((y0, paragraph))
            run = paragraph.add_run(text)
            run.font.name = "Arial"
            run.font.size = Pt(height_pt)
            run.bold = line.get("region") == "heading"
            r_pr = run._element.get_or_add_rPr()
            r_fonts = r_pr.rFonts
            if r_fonts is not None:
                r_fonts.set(qn("w:cs"), "Arial")
            if any(0x0600 <= ord(char) <= 0x06ff for char in text):
                rtl = OxmlElement("w:rtl")
                rtl.set(qn("w:val"), "1")
                r_pr.append(rtl)
                lang = OxmlElement("w:lang")
                lang.set(qn("w:val"), "ar-SA")
                lang.set(qn("w:bidi"), "ar-SA")
                r_pr.append(lang)
            previous_bottom = max(previous_bottom, y1)

        # Insert detected tables as real Word tables at their vertical reading position.
        # Process lower tables first so multiple insertions before one paragraph remain ordered.
        for x0, y0, x1, y1, table_data in sorted(table_regions, key=lambda item: item[1], reverse=True):
            table = _append_ocr_word_table(document, table_data, table_data.get("direction", direction))
            if table is None:
                continue
            anchor = next((paragraph for line_y, paragraph in paragraph_positions if line_y > y0), None)
            if anchor is not None:
                anchor._p.addprevious(table._tbl)

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


def _docx_text_parts(document) -> list[str]:
    """Collect paragraph/table text without counting merged grid cells repeatedly."""
    parts = [paragraph.text for paragraph in document.paragraphs]
    seen_cells = set()
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                cell_xml = cell._tc
                if cell_xml in seen_cells:
                    continue
                seen_cells.add(cell_xml)
                parts.append(cell.text)
    return parts


def analyze_pdf_docx_quality(pdf_bytes: bytes, docx_bytes: bytes, source_text_override: str | None = None) -> dict:
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
        "source_text_basis": "native-pdf",
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
        output_parts = _docx_text_parts(converted)
        report["output_paragraph_count"] = len(converted.paragraphs)
        report["output_table_count"] = len(converted.tables)
        report["output_image_count"] = len(converted.inline_shapes)

        def tokens(value):
            normalized = unicodedata.normalize("NFKC", value).casefold()
            return re.findall(r"\w+", normalized, flags=re.UNICODE)

        native_source_text = "\n".join(source_parts)
        if isinstance(source_text_override, str) and source_text_override.strip():
            # Compare against the exact OCR text stream used to reconstruct scanned
            # pages. This measures DOCX text retention, not OCR accuracy vs ground truth.
            source_text = source_text_override[:1_500_000]
            report["source_text_basis"] = "ocr-reconstruction"
        else:
            source_text = native_source_text
        source_tokens = tokens(source_text)
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
