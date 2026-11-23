import unittest

import pymupdf
from PIL import Image
import io

from pdf_tools import compress_pdf_bytes


class PdfCompressionTests(unittest.TestCase):
    def make_pdf(self):
        document = pymupdf.open()
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 90), "Alfalqi PDF compression test")
        page.insert_text((72, 120), "Second line remains selectable")
        return document.tobytes(garbage=0, deflate=False, use_objstms=0)

    def test_compression_returns_valid_pdf_and_preserves_text(self):
        source = self.make_pdf()
        result, reduced = compress_pdf_bytes(source)
        self.assertIsInstance(reduced, bool)
        self.assertLessEqual(len(result), len(source))
        with pymupdf.open(stream=result, filetype="pdf") as document:
            self.assertEqual(document.page_count, 1)
            text = document[0].get_text()
            self.assertIn("Alfalqi PDF compression test", text)
            self.assertIn("Second line remains selectable", text)

    def test_small_profile_reduces_embedded_scan_and_preserves_text(self):
        document = pymupdf.open()
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 90), "Searchable text remains available")
        image = Image.effect_noise((1800, 2400), 90).convert("RGB")
        image_data = io.BytesIO()
        image.save(image_data, format="PNG")
        page.insert_image(page.rect, stream=image_data.getvalue())
        source = document.tobytes(garbage=0, deflate=False, use_objstms=0)
        document.close()

        result, reduced = compress_pdf_bytes(source, "small")
        self.assertTrue(reduced)
        self.assertLess(len(result), len(source))
        with pymupdf.open(stream=result, filetype="pdf") as optimized:
            self.assertEqual(optimized.page_count, 1)
            self.assertIn("Searchable text remains available", optimized[0].get_text())
            self.assertTrue(optimized[0].get_images())

    def test_invalid_compression_level_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "مستوى الضغط"):
            compress_pdf_bytes(self.make_pdf(), "ultra")

    def test_invalid_pdf_is_rejected(self):
        with self.assertRaises(ValueError):
            compress_pdf_bytes(b"not a pdf")

    def test_password_protected_pdf_is_rejected(self):
        document = pymupdf.open()
        document.new_page()
        encrypted = document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )
        document.close()
        with self.assertRaisesRegex(ValueError, "كلمة مرور"):
            compress_pdf_bytes(encrypted)

    def test_empty_pdf_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "فارغ"):
            compress_pdf_bytes(b"")


if __name__ == "__main__":
    unittest.main()
