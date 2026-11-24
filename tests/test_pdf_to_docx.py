import io
import unittest

import pymupdf
from docx import Document

from pdf_to_docx import convert_pdf_to_docx


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
