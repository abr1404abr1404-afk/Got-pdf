import io
import unittest

from document_export import _clean_pages, create_docx, create_xlsx


class DocumentExportTests(unittest.TestCase):
    def test_docx_is_valid_and_contains_page_text(self):
        from docx import Document
        data = create_docx([{"page": 3, "text": "مرحبا بالعالم\nسطر ثان"}])
        document = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in document.paragraphs)
        self.assertIn("الصفحة 3", text)
        self.assertIn("مرحبا بالعالم", text)

    def test_xlsx_is_valid_and_rows_are_page_scoped(self):
        from openpyxl import load_workbook
        data = create_xlsx([{"page": 2, "text": "سطر أول\nسطر ثان"}])
        workbook = load_workbook(io.BytesIO(data), read_only=True)
        rows = list(workbook.active.values)
        self.assertEqual(rows[0], ("رقم الصفحة", "رقم السطر", "النص"))
        self.assertEqual(rows[1], (2, 1, "سطر أول"))
        self.assertEqual(rows[2], (2, 2, "سطر ثان"))

    def test_rejects_empty_and_oversized_exports(self):
        with self.assertRaises(ValueError):
            _clean_pages([])
        with self.assertRaises(ValueError):
            _clean_pages([{"page": 1, "text": "x" * 200001}])

    def test_rejects_invalid_page_data(self):
        with self.assertRaises(ValueError):
            _clean_pages([{"page": 0, "text": "text"}])
        with self.assertRaises(ValueError):
            _clean_pages([{"page": 1, "text": 123}])


if __name__ == "__main__":
    unittest.main()
