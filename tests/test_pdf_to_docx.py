import io
import unittest

import pymupdf
from docx import Document

from pdf_to_docx import convert_pdf_to_docx, analyze_pdf_docx_quality


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
        self.assertEqual(report["text_precision_percent"], 66.67)
        self.assertEqual(report["output_table_count"], 1)
        self.assertEqual(report["output_paragraph_count"], 1)
        self.assertGreater(report["source_word_count"], 0)

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
