import unittest

import pymupdf

import main


class NativePdfTextTests(unittest.TestCase):
    def test_searchable_pdf_uses_embedded_text_without_raster_ocr(self):
        document = pymupdf.open()
        page = document.new_page(width=595, height=842)
        page.insert_text(
            (60, 90),
            "A searchable PDF paragraph with enough characters to use its native text layer.",
            fontsize=12,
        )

        result = main._native_pdf_page_result(page, 1.5)
        document.close()

        self.assertIsNotNone(result)
        self.assertEqual(result["engine"], "native-pdf-text")
        self.assertTrue(result["lines"])
        self.assertEqual(result["lines"][0]["engine"], "pdf-text")
        self.assertGreater(result["image_width"], 595)
        self.assertEqual(result["engines"]["tesseract"]["available"], False)

    def test_scanned_or_empty_pdf_page_falls_back_to_ocr(self):
        document = pymupdf.open()
        page = document.new_page(width=595, height=842)

        result = main._native_pdf_page_result(page, 1.5)
        document.close()

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
