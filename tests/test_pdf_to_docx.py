import io
import unittest
from unittest.mock import patch

import pymupdf
from docx import Document

from pdf_to_docx import convert_pdf_to_docx, analyze_pdf_docx_quality, _apply_arabic_direction, _docx_text_parts


class PdfToDocxTests(unittest.TestCase):
    def test_converts_selectable_text_to_valid_docx(self):
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Editable PDF to Word", fontsize=16)
        source = doc.tobytes()
        doc.close()
        result = convert_pdf_to_docx(source)
        converted = Document(io.BytesIO(result))
        text = "\n".join(paragraph.text for paragraph in converted.paragraphs)
        self.assertIn("Editable PDF to Word", text)


    def test_quality_report_measures_text_and_tables(self):
        source_doc = pymupdf.open()
        page = source_doc.new_page()
        page.insert_text((72, 100), "Arabic quality report 123", fontsize=12)
        source = source_doc.tobytes()
        source_doc.close()

        output_doc = Document()
        output_doc.add_paragraph("Arabic quality report 123")
        table = output_doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Name"
        table.cell(0, 1).text = "Value"
        buffer = io.BytesIO()
        output_doc.save(buffer)

        report = analyze_pdf_docx_quality(source, buffer.getvalue())

        self.assertEqual(report["analysis_status"], "ok")
        self.assertTrue(report["source_extractable"])
        self.assertEqual(report["text_coverage_percent"], 100.0)
        self.assertEqual(report["output_table_count"], 1)
        self.assertEqual(report["output_paragraph_count"], 1)
        self.assertGreater(report["source_word_count"], 0)


    def test_quality_report_does_not_double_count_merged_table_cells(self):
        source_doc = pymupdf.open()
        page = source_doc.new_page()
        page.insert_text((72, 100), "Name Value", fontsize=12)
        source = source_doc.tobytes()
        source_doc.close()

        output_doc = Document()
        table = output_doc.add_table(rows=1, cols=2)
        merged = table.cell(0, 0).merge(table.cell(0, 1))
        merged.text = "Name Value"

        parts = _docx_text_parts(output_doc)
        self.assertEqual(parts, ["Name Value"])
        buffer = io.BytesIO()
        output_doc.save(buffer)
        report = analyze_pdf_docx_quality(source, buffer.getvalue())

        self.assertEqual(report["output_word_count"], 2)
        self.assertEqual(report["matched_word_count"], 2)
        self.assertEqual(report["text_precision_percent"], 100.0)

    def test_quality_report_marks_scanned_pdf_without_extractable_text(self):
        source_doc = pymupdf.open()
        source_doc.new_page()
        source = source_doc.tobytes()
        source_doc.close()

        output_doc = Document()
        output_doc.add_paragraph("OCR text")
        buffer = io.BytesIO()
        output_doc.save(buffer)

        report = analyze_pdf_docx_quality(source, buffer.getvalue())

        self.assertEqual(report["analysis_status"], "no_extractable_source_text")
        self.assertIsNone(report["text_coverage_percent"])
        self.assertFalse(report["source_extractable"])


    def test_arabic_paragraphs_get_word_rtl_metadata(self):
        from docx.oxml.ns import qn

        source = Document()
        source.add_paragraph("هذا نص عربي للاختبار")
        source.add_paragraph("English paragraph")
        buffer = io.BytesIO()
        source.save(buffer)

        result = _apply_arabic_direction(buffer.getvalue())
        converted = Document(io.BytesIO(result))
        arabic_ppr = converted.paragraphs[0]._p.pPr
        english_ppr = converted.paragraphs[1]._p.pPr

        self.assertIsNotNone(arabic_ppr.find(qn("w:bidi")))
        self.assertTrue(
            english_ppr is None or english_ppr.find(qn("w:bidi")) is None
        )


    def test_scanned_pdf_uses_ocr_and_creates_editable_rtl_word(self):
        from PIL import Image
        import main

        image_buffer = io.BytesIO()
        Image.new("RGB", (300, 420), "white").save(image_buffer, format="PNG")
        source_doc = pymupdf.open()
        page = source_doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=image_buffer.getvalue())
        source = source_doc.tobytes()
        source_doc.close()

        fake_ocr = {
            "engine": "tesseract",
            "image_width": 1488,
            "image_height": 2105,
            "lines": [{
                "text": "هذا نص عربي تجريبي",
                "confidence": 96.0,
                "bbox": [120, 180, 720, 230],
                "engine": "tesseract",
                "region": "body",
                "column": 1,
            }],
            "layout": {"direction": "rtl"},
        }
        with patch.object(main, "_hybrid", return_value=fake_ocr), patch.object(
            main, "_detect_tables", return_value=[]
        ):
            output, engine = main._convert_pdf_to_docx_adaptive(source)

        converted = Document(io.BytesIO(output))
        text = "\\n".join(paragraph.text for paragraph in converted.paragraphs)
        self.assertEqual(engine, "ocr-layout")
        self.assertIn("هذا نص عربي تجريبي", text)
        self.assertTrue(any(paragraph._p.pPr is not None for paragraph in converted.paragraphs))

    def test_ocr_docx_uses_explicit_rtl_reading_order(self):
        from pdf_to_docx import create_ocr_docx

        pages = [{
            "direction": "rtl",
            "dpi": 180,
            "lines": [
                {"text": "يسار أعلى", "bbox": [10, 80, 140, 100], "column": 2, "reading_order": 3},
                {"text": "يمين أعلى", "bbox": [260, 80, 390, 100], "column": 1, "reading_order": 1},
                {"text": "يسار أسفل", "bbox": [10, 130, 140, 150], "column": 2, "reading_order": 4},
                {"text": "يمين أسفل", "bbox": [260, 130, 390, 150], "column": 1, "reading_order": 2},
            ],
        }]
        converted = Document(io.BytesIO(create_ocr_docx(pages)))
        self.assertEqual(
            [paragraph.text for paragraph in converted.paragraphs],
            ["يمين أعلى", "يمين أسفل", "يسار أعلى", "يسار أسفل"],
        )

    def test_native_pdf_line_merge_keeps_columns_separate(self):
        import main

        lines = [
            {"text": "كلمة", "bbox": [100, 20, 150, 40], "column": 1, "region": "body", "direction": "rtl", "reading_order": 1},
            {"text": "أولى", "bbox": [40, 20, 90, 40], "column": 1, "region": "body", "direction": "rtl", "reading_order": 2},
            {"text": "عمود", "bbox": [300, 20, 360, 40], "column": 2, "region": "body", "direction": "rtl", "reading_order": 3},
        ]
        merged = main._merge_native_pdf_lines(lines)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["text"], "كلمة أولى")
        self.assertEqual(merged[1]["text"], "عمود")

    def test_native_simple_route_rejects_tables_and_multiple_columns(self):
        from types import SimpleNamespace
        import main

        page = SimpleNamespace(get_images=lambda full=True: [], find_tables=lambda: SimpleNamespace(tables=[]))
        simple = {"layout": {"column_count": 1}, "lines": [{"bbox": [1, 1, 20, 10], "text": "نص"}]}
        self.assertTrue(main._native_pdf_page_is_simple(page, simple))

        table_page = SimpleNamespace(get_images=lambda full=True: [], find_tables=lambda: SimpleNamespace(tables=[object()]))
        self.assertFalse(main._native_pdf_page_is_simple(table_page, simple))
        multi_column = {"layout": {"column_count": 2}, "lines": simple["lines"]}
        self.assertFalse(main._native_pdf_page_is_simple(page, multi_column))

    def test_native_simple_route_rejects_pages_with_images(self):
        from types import SimpleNamespace
        import main

        page = SimpleNamespace(get_images=lambda full=True: [(1,)], find_tables=lambda: SimpleNamespace(tables=[]))
        result = {"layout": {"column_count": 1}, "lines": [{"bbox": [1, 1, 20, 10], "text": "نص"}]}
        self.assertFalse(main._native_pdf_page_is_simple(page, result))

    def test_ocr_docx_preserves_source_pdf_page_dimensions(self):
        from pdf_to_docx import create_ocr_docx
        from docx.shared import Pt

        converted = Document(io.BytesIO(create_ocr_docx([{
            "direction": "rtl",
            "dpi": 240,
            "page_width_pt": 420,
            "page_height_pt": 595,
            "lines": [{
                "text": "مستند عربي",
                "bbox": [100, 100, 500, 150],
                "column": 1,
                "reading_order": 1,
            }],
        }])))
        section = converted.sections[0]
        self.assertAlmostEqual(section.page_width.pt, 420, delta=0.1)
        self.assertAlmostEqual(section.page_height.pt, 595, delta=0.1)
        self.assertAlmostEqual(section.top_margin.pt, 0, delta=0.1)
        self.assertAlmostEqual(section.right_margin.pt, 0, delta=0.1)

    def test_rejects_more_than_twenty_pages(self):
        doc = pymupdf.open()
        for _ in range(21):
            doc.new_page()
        source = doc.tobytes()
        doc.close()
        with self.assertRaises(ValueError):
            convert_pdf_to_docx(source)


if __name__ == "__main__":
    unittest.main()
