import unittest

import pymupdf

from pdf_image_tools import list_pdf_images, edit_pdf_images


class PdfImageToolsTests(unittest.TestCase):
    def source_pdf(self):
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=200)
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 30, 20), 0)
        pix.clear_with(0xCC2222)
        page.insert_image(pymupdf.Rect(60, 50, 180, 130), pixmap=pix)
        page.insert_text((30, 180), "Keep this text")
        data = doc.tobytes()
        doc.close()
        return data

    def test_list_images_returns_occurrence_and_preview(self):
        items = list_pdf_images(self.source_pdf())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["page"], 1)
        self.assertEqual(items[0]["width"], 30)
        self.assertTrue(items[0]["data"])
        self.assertEqual(len(items[0]["rect"]), 4)

    def test_delete_image_keeps_text(self):
        source = self.source_pdf()
        item = list_pdf_images(source)[0]
        output = edit_pdf_images(source, [{
            "page": item["page"], "xref": item["xref"],
            "occurrence": item["occurrence"], "rect": item["rect"],
            "action": "delete",
        }])
        with pymupdf.open(stream=output, filetype="pdf") as doc:
            self.assertIn("Keep this text", doc[0].get_text())
            pix = doc[0].get_pixmap(alpha=False)
            self.assertGreater(pix.pixel(100, 80)[0], 180)

    def test_resize_image_changes_its_placement_size(self):
        source = self.source_pdf()
        item = list_pdf_images(source)[0]
        output = edit_pdf_images(source, [{
            "page": item["page"], "xref": item["xref"],
            "occurrence": item["occurrence"], "rect": item["rect"],
            "action": "resize", "scale": 0.5,
        }])
        with pymupdf.open(stream=output, filetype="pdf") as doc:
            rects = doc[0].get_image_rects(doc[0].get_images(full=True)[0][0])
            self.assertTrue(rects)
            self.assertAlmostEqual(rects[0].width, 60, delta=2)
            self.assertAlmostEqual(rects[0].height, 40, delta=2)

    def test_invalid_scale_is_rejected(self):
        source = self.source_pdf()
        item = list_pdf_images(source)[0]
        with self.assertRaises(ValueError):
            edit_pdf_images(source, [{
                "page": 1, "xref": item["xref"], "occurrence": 0,
                "rect": item["rect"], "action": "resize", "scale": 8,
            }])


if __name__ == "__main__":
    unittest.main()
