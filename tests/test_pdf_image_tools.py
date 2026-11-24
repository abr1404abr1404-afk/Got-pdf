import unittest

import pymupdf

from pdf_image_tools import list_pdf_images, edit_pdf_images, inspect_pdf_objects, edit_pdf_vector_objects


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

    def test_inspect_includes_text_font_and_style_metadata(self):
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((30, 50), "Metadata sample", fontname="helv", fontsize=14, color=(0.2, 0.3, 0.4))
        source = doc.tobytes()
        doc.close()
        report = inspect_pdf_objects(source)
        item = next(item for item in report["objects"] if item["type"] == "text")
        self.assertTrue(item["font"])
        self.assertAlmostEqual(item["font_size"], 14, delta=0.2)
        self.assertEqual(item["color"], "#334C66")
        self.assertEqual(len(item["writing_direction"]), 2)
        self.assertEqual(len(item["origin"]), 2)

    def test_inspect_flags_vector_text_overlap(self):
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((90, 90), "Overlap")
        page.draw_rect(pymupdf.Rect(85, 65, 175, 100), color=(1, 0, 0), width=2)
        source = doc.tobytes()
        doc.close()
        report = inspect_pdf_objects(source)
        self.assertTrue(any(w["type"] == "vector_text_overlap" for w in report["warnings"]))

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


    def vector_source(self, overlap_text=False):
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((30, 30), "Keep this text")
        if overlap_text:
            page.insert_text((90, 90), "Do not cover")
            page.draw_rect(pymupdf.Rect(85, 65, 175, 100), color=(1, 0, 0), width=2)
        else:
            page.draw_rect(pymupdf.Rect(30, 60, 80, 100), color=(1, 0, 0), width=2)
            page.draw_rect(pymupdf.Rect(190, 60, 240, 100), color=(0, 0, 1), width=2)
        data = doc.tobytes()
        doc.close()
        return data

    def test_delete_isolated_vector_preserves_other_drawing_and_text(self):
        source = self.vector_source()
        report = inspect_pdf_objects(source)
        vectors = [item for item in report["objects"] if item["type"] == "vector"]
        self.assertEqual(len(vectors), 2)
        output = edit_pdf_vector_objects(source, [{
            "page": vectors[0]["page"], "object_id": vectors[0]["id"],
            "rect": vectors[0]["rect"], "action": "delete",
        }])
        with pymupdf.open(stream=output, filetype="pdf") as doc:
            self.assertIn("Keep this text", doc[0].get_text())
            self.assertEqual(len(doc[0].get_drawings()), 1)
        with pymupdf.open(stream=source, filetype="pdf") as original:
            self.assertEqual(len(original[0].get_drawings()), 2)

    def test_vector_delete_rejects_overlap_with_text(self):
        source = self.vector_source(overlap_text=True)
        report = inspect_pdf_objects(source)
        vector = next(item for item in report["objects"] if item["type"] == "vector")
        with self.assertRaisesRegex(ValueError, "يتداخل مع نص"):
            edit_pdf_vector_objects(source, [{
                "page": vector["page"], "object_id": vector["id"],
                "rect": vector["rect"], "action": "delete",
            }])

    def test_vector_delete_rejects_stale_object_id(self):
        source = self.vector_source()
        with self.assertRaises(ValueError):
            edit_pdf_vector_objects(source, [{
                "page": 1, "object_id": "p1-vector-99",
                "rect": [0.1, 0.1, 0.2, 0.2], "action": "delete",
            }])



if __name__ == "__main__":
    unittest.main()

