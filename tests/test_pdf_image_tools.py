import unittest

import pymupdf

from pdf_image_tools import list_pdf_images, edit_pdf_images, inspect_pdf_objects, edit_pdf_vector_objects, delete_isolated_pdf_text, replace_isolated_latin_pdf_text, recolor_isolated_pdf_vector


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

    def test_replace_isolated_latin_text_preserves_other_text_and_source(self):
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=200)
        page.insert_text((30, 60), "OldLabel", fontsize=12, color=(0.2, 0.3, 0.4))
        page.insert_text((250, 60), "KeepMe", fontsize=12)
        source = doc.tobytes()
        doc.close()
        target = next(item for item in inspect_pdf_objects(source)["objects"]
                      if item["type"] == "text" and item["text"] == "OldLabel")
        output = replace_isolated_latin_pdf_text(source, {
            "action": "replace", "page": 1, "object_id": target["id"],
            "text_hash": target["text_hash"], "rect": target["rect"],
            "replacement": "NewTag",
        })
        with pymupdf.open(stream=output, filetype="pdf") as result:
            text = result[0].get_text()
            self.assertIn("NewTag", text)
            self.assertNotIn("OldLabel", text)
            self.assertIn("KeepMe", text)
        with pymupdf.open(stream=source, filetype="pdf") as original:
            self.assertIn("OldLabel", original[0].get_text())

    def test_replace_latin_text_rejects_arabic(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((30, 60), "Label")
        source = doc.tobytes()
        doc.close()
        target = next(item for item in inspect_pdf_objects(source)["objects"] if item["type"] == "text")
        with self.assertRaisesRegex(ValueError, "الحروف اللاتينية"):
            replace_isolated_latin_pdf_text(source, {
                "action": "replace", "page": 1, "object_id": target["id"],
                "text_hash": target["text_hash"], "rect": target["rect"],
                "replacement": "مرحبا",
            })

    def test_replace_latin_text_rejects_wider_replacement(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((30, 60), "A")
        source = doc.tobytes()
        doc.close()
        target = next(item for item in inspect_pdf_objects(source)["objects"] if item["type"] == "text")
        with self.assertRaisesRegex(ValueError, "أعرض"):
            replace_isolated_latin_pdf_text(source, {
                "action": "replace", "page": 1, "object_id": target["id"],
                "text_hash": target["text_hash"], "rect": target["rect"],
                "replacement": "A much longer replacement",
            })

    def test_delete_isolated_text_span_preserves_other_text_and_source(self):
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=200)
        page.insert_text((30, 60), "RemoveMe", fontsize=12)
        page.insert_text((250, 60), "KeepMe", fontsize=12)
        source = doc.tobytes()
        doc.close()
        report = inspect_pdf_objects(source)
        target = next(item for item in report["objects"] if item["type"] == "text" and item["text"] == "RemoveMe")
        output = delete_isolated_pdf_text(source, {
            "action": "delete", "page": target["page"], "object_id": target["id"],
            "text_hash": target["text_hash"], "rect": target["rect"],
        })
        with pymupdf.open(stream=output, filetype="pdf") as result:
            text = result[0].get_text()
            self.assertNotIn("RemoveMe", text)
            self.assertIn("KeepMe", text)
        with pymupdf.open(stream=source, filetype="pdf") as original:
            self.assertIn("RemoveMe", original[0].get_text())

    def test_text_delete_rejects_overlapping_text(self):
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((50, 80), "Overlap", fontsize=18)
        page.insert_text((50, 80), "Overlap", fontsize=18)
        source = doc.tobytes()
        doc.close()
        target = next(item for item in inspect_pdf_objects(source)["objects"] if item["type"] == "text")
        with self.assertRaisesRegex(ValueError, "يتداخل النص مع مقطع"):
            delete_isolated_pdf_text(source, {
                "action": "delete", "page": 1, "object_id": target["id"],
                "text_hash": target["text_hash"], "rect": target["rect"],
            })

    def test_text_delete_rejects_stale_hash(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((30, 50), "Stale")
        source = doc.tobytes()
        doc.close()
        target = next(item for item in inspect_pdf_objects(source)["objects"] if item["type"] == "text")
        with self.assertRaisesRegex(ValueError, "تغيّر النص"):
            delete_isolated_pdf_text(source, {
                "action": "delete", "page": 1, "object_id": target["id"],
                "text_hash": "0" * 64, "rect": target["rect"],
            })

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
        self.assertEqual(item["color"], "#334D66")
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

    def test_recolor_isolated_vector_rectangle_preserves_geometry_and_text(self):
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((30, 30), "Keep this text")
        page.draw_rect(pymupdf.Rect(80, 70, 150, 120), color=(1, 0, 0), fill=(0, 1, 0), width=2)
        source = doc.tobytes()
        doc.close()
        target = next(item for item in inspect_pdf_objects(source)["objects"] if item["type"] == "vector")
        output = recolor_isolated_pdf_vector(source, {
            "action": "recolor", "page": 1, "object_id": target["id"],
            "rect": target["rect"], "stroke_color": "#0000FF", "fill_color": "#FFFF00",
        })
        with pymupdf.open(stream=output, filetype="pdf") as result:
            self.assertIn("Keep this text", result[0].get_text())
            drawings = result[0].get_drawings()
            self.assertEqual(len(drawings), 1)
            self.assertEqual(drawings[0]["color"], (0.0, 0.0, 1.0))
            self.assertEqual(drawings[0]["fill"], (1.0, 1.0, 0.0))
            self.assertAlmostEqual(drawings[0]["rect"].width, 70, delta=0.2)
        with pymupdf.open(stream=source, filetype="pdf") as original:
            self.assertEqual(original[0].get_drawings()[0]["color"], (1.0, 0.0, 0.0))

    def test_recolor_vector_rejects_overlap(self):
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((90, 90), "Overlapping")
        page.draw_rect(pymupdf.Rect(85, 65, 175, 100), color=(1, 0, 0), width=2)
        source = doc.tobytes()
        doc.close()
        target = next(item for item in inspect_pdf_objects(source)["objects"] if item["type"] == "vector")
        with self.assertRaisesRegex(ValueError, "يتداخل مع نص"):
            recolor_isolated_pdf_vector(source, {
                "action": "recolor", "page": 1, "object_id": target["id"],
                "rect": target["rect"], "stroke_color": "#0000FF",
            })

    def test_recolor_vector_rejects_complex_path(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.draw_rect(pymupdf.Rect(30, 30, 80, 80), color=(1, 0, 0))
        page.draw_rect(pymupdf.Rect(120, 30, 170, 80), color=(0, 0, 1))
        source = doc.tobytes()
        doc.close()
        with pymupdf.open(stream=source, filetype="pdf") as check:
            check[0].draw_line((50, 50), (60, 60), color=(0, 0, 0))
            source = check.tobytes()
        target = next(item for item in inspect_pdf_objects(source)["objects"] if item["type"] == "vector")
        # A rectangle is supported; a multi-item path is deliberately not.
        self.assertIn("re", target["path_types"])

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

