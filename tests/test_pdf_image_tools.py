import unittest

import pymupdf

from pdf_image_tools import list_pdf_images, edit_pdf_images, inspect_pdf_objects


class PdfImageToolsTests(unittest.TestCase):
    def source_pdf(self):
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=200)
        from PIL import Image
        import io
        image = Image.new("RGB", (30, 20), (220, 34, 34))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        page.insert_image(pymupdf.Rect(60, 50, 180, 130), stream=buffer.getvalue())
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

    def test_inspect_reports_text_images_and_vector_objects(self):
        source = self.source_pdf()
        with pymupdf.open(stream=source, filetype="pdf") as doc:
            doc[0].draw_rect(pymupdf.Rect(200, 40, 260, 90), color=(0, 0, 1), fill=(0, 1, 0))
            source = doc.tobytes()
        report = inspect_pdf_objects(source)
        self.assertEqual(report["pages"], 1)
        self.assertGreaterEqual(report["counts"]["text"], 1)
        self.assertGreaterEqual(report["counts"]["image"], 1)
        self.assertGreaterEqual(report["counts"]["vector"], 1)
        self.assertTrue(all(len(item["rect"]) == 4 for item in report["objects"]))

    def test_inspect_flags_image_text_overlap(self):
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=200)
        from PIL import Image
        import io
        image = Image.new("RGB", (30, 20), (220, 34, 34))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        page.insert_image(pymupdf.Rect(30, 40, 180, 120), stream=buffer.getvalue())
        page.insert_text((60, 80), "Overlapping text")
        source = doc.tobytes()
        doc.close()
        report = inspect_pdf_objects(source)
        self.assertTrue(any(w["type"] == "image_text_overlap" for w in report["warnings"]))



if __name__ == "__main__":
    unittest.main()



if __name__ == "__main__":
    unittest.main()
