import unittest

import pymupdf

from searchable_pdf import add_searchable_text_layer, _validated_pages


class SearchablePdfTests(unittest.TestCase):
    def make_pdf(self):
        document = pymupdf.open()
        document.new_page(width=595, height=842)
        data = document.tobytes()
        document.close()
        return data

    def test_english_text_layer_is_invisible_and_searchable(self):
        source = self.make_pdf()
        result = add_searchable_text_layer(source, {
            "pages": [{"page": 1, "lines": [{"text": "Searchable PDF sample", "bbox": [60, 80, 250, 100]}]}]
        })
        with pymupdf.open(stream=result, filetype="pdf") as document:
            page = document[0]
            self.assertIn("Searchable PDF sample", page.get_text())
            self.assertTrue(page.search_for("Searchable"))
            span = page.get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
            self.assertEqual(span["alpha"], 0)

    def test_arabic_text_layer_preserves_logical_search_text(self):
        source = self.make_pdf()
        try:
            result = add_searchable_text_layer(source, {
                "pages": [{"page": 1, "lines": [{"text": "مرحبا بالعالم", "bbox": [60, 80, 250, 100]}]}]
            })
        except ValueError as exc:
            if "خط العربية غير متوفر" in str(exc):
                self.skipTest("Noto Arabic font is not installed in this environment")
            raise
        with pymupdf.open(stream=result, filetype="pdf") as document:
            text = document[0].get_text()
            self.assertIn("مرحبا بالعالم", text)
            self.assertTrue(document[0].search_for("مرحبا"))

    def test_mixed_arabic_and_latin_text_is_extractable(self):
        source = self.make_pdf()
        result = add_searchable_text_layer(source, {
            "pages": [{"page": 1, "lines": [{"text": "رقم 123 ABC", "bbox": [60, 80, 250, 100]}]}]
        })
        with pymupdf.open(stream=result, filetype="pdf") as document:
            self.assertIn("رقم 123 ABC", document[0].get_text())

    def test_invalid_page_and_empty_lines_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "خارج نطاق"):
            _validated_pages({"pages": [{"page": 2, "lines": []}]}, 1)
        with self.assertRaisesRegex(ValueError, "لا توجد أسطر"):
            _validated_pages({"pages": [{"page": 1, "lines": []}]}, 1)

    def test_invalid_boxes_are_ignored_and_oversized_text_rejected(self):
        payload = {"pages": [{"page": 1, "lines": [
            {"text": "bad box", "bbox": [1, 2, 1, 3]},
            {"text": "x" * 1001, "bbox": [1, 2, 10, 12]},
        ]}]}
        with self.assertRaisesRegex(ValueError, "لا توجد أسطر"):
            _validated_pages(payload, 1)


if __name__ == "__main__":
    unittest.main()
