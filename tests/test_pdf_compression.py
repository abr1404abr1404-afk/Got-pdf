import unittest

import fitz

from pdf_tools import compress_pdf_bytes


class PdfCompressionTests(unittest.TestCase):
    def make_pdf(self):
        document = fitz.open()
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 90), "Alfalqi PDF compression test")
        page.insert_text((72, 120), "اختبار الحفاظ على النص")
        return document.tobytes(garbage=0, deflate=False, use_objstms=0)

    def test_compression_returns_valid_pdf_and_preserves_text(self):
        source = self.make_pdf()
        result, reduced = compress_pdf_bytes(source)
        self.assertIsInstance(reduced, bool)
        self.assertLessEqual(len(result), len(source))
        with fitz.open(stream=result, filetype="pdf") as document:
            self.assertEqual(document.page_count, 1)
            text = document[0].get_text()
            self.assertIn("Alfalqi PDF compression test", text)
            self.assertIn("اختبار الحفاظ على النص", text)

    def test_invalid_pdf_is_rejected(self):
        with self.assertRaises(ValueError):
            compress_pdf_bytes(b"not a pdf")

    def test_empty_pdf_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "فارغ"):
            compress_pdf_bytes(b"")


if __name__ == "__main__":
    unittest.main()
