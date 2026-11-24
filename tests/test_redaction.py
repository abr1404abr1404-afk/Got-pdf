import unittest

import pymupdf

from redaction import _parse_regions, redact_pdf_bytes


class RedactionTests(unittest.TestCase):
    def make_pdf(self):
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((40, 80), "SECRET-CODE-9281", fontsize=18)
        page.insert_text((40, 150), "PUBLIC TEXT", fontsize=12)
        data = doc.tobytes()
        doc.close()
        return data

    def test_redaction_removes_text_from_extraction_and_search(self):
        source = self.make_pdf()
        result = redact_pdf_bytes(source, {
            "regions": [{"page": 1, "rect": [0.10, 0.25, 0.72, 0.48]}]
        })
        with pymupdf.open(stream=result, filetype="pdf") as doc:
            text = doc[0].get_text()
            self.assertNotIn("SECRET-CODE-9281", text)
            self.assertFalse(doc[0].search_for("SECRET-CODE"))
            self.assertIn("PUBLIC TEXT", text)

    def test_redaction_blanks_overlapping_image_pixels_and_removes_vector_graphics(self):
        from PIL import Image
        import io

        image = Image.new("RGB", (40, 40), (220, 30, 30))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=200)
        page.insert_image(pymupdf.Rect(40, 50, 140, 150), stream=buffer.getvalue())
        page.draw_rect(pymupdf.Rect(160, 50, 250, 150), color=(0, 0, 1), fill=(0, 0, 1))
        source = doc.tobytes()
        doc.close()

        result = redact_pdf_bytes(source, {
            "regions": [{"page": 1, "rect": [0.15, 0.25, 0.33, 0.75]}]
        })
        with pymupdf.open(stream=result, filetype="pdf") as output:
            page = output[0]
            pix = page.get_pixmap(alpha=False)
            inside = pix.pixel(70, 100)
            outside = pix.pixel(120, 100)
            self.assertLess(max(inside[:3]), 20)
            self.assertGreater(outside[0], outside[1] * 2)
            self.assertFalse(any(d["rect"].intersects(pymupdf.Rect(160, 50, 250, 150))
                                 for d in page.get_drawings()))

    def test_redaction_regions_are_page_scoped_and_validated(self):
        grouped = _parse_regions({"regions": [
            {"page": 1, "rect": [0.1, 0.1, 0.2, 0.2]},
            {"page": 2, "rect": [0.3, 0.3, 0.4, 0.4]},
        ]}, 2)
        self.assertEqual(len(grouped[0]), 1)
        self.assertEqual(len(grouped[1]), 1)

    def test_rejects_out_of_bounds_and_non_finite_coordinates(self):
        for rect in ([0, 0, 1.1, 1], [0.5, 0.2, 0.4, 0.7],
                     [0, 0, float("nan"), 1]):
            with self.subTest(rect=rect):
                with self.assertRaises(ValueError):
                    _parse_regions({"regions": [{"page": 1, "rect": rect}]}, 1)

    def test_rejects_invalid_page_and_empty_regions(self):
        with self.assertRaisesRegex(ValueError, "خارج نطاق"):
            _parse_regions({"regions": [{"page": 2, "rect": [0, 0, 0.2, 0.2]}]}, 1)
        with self.assertRaises(ValueError):
            _parse_regions({"regions": []}, 1)

    def test_invalid_pdf_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "ليس PDF"):
            redact_pdf_bytes(b"not a pdf", {"regions": [{"page": 1, "rect": [0, 0, 1, 1]}]})


if __name__ == "__main__":
    unittest.main()
