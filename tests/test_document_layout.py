import unittest

from document_layout import analyze_layout, attach_table_regions


def line(text, box):
    return {"text": text, "bbox": box, "confidence": 90.0}


class DocumentLayoutTests(unittest.TestCase):
    def test_arabic_page_direction_and_line_metadata(self):
        result = analyze_layout([
            line("عنوان المستند", [40, 10, 360, 42]),
            line("هذا نص عربي", [40, 70, 350, 92]),
        ], 400, 600)
        self.assertEqual(result["direction"], "rtl")
        self.assertEqual(result["column_count"], 1)
        self.assertEqual(result["lines"][0]["region"], "heading")
        self.assertEqual(result["lines"][1]["region"], "body")
        self.assertEqual(result["lines"][0]["column"], 1)

    def test_english_page_direction(self):
        result = analyze_layout([
            line("Document title", [20, 10, 300, 40]),
            line("This is a paragraph.", [20, 70, 350, 90]),
        ], 400, 600)
        self.assertEqual(result["direction"], "ltr")

    def test_two_columns_are_detected(self):
        rows = [
            line("عمود يمين 1", [260, 80, 390, 100]),
            line("عمود يسار 1", [10, 80, 140, 100]),
            line("عمود يمين 2", [260, 130, 390, 150]),
            line("عمود يسار 2", [10, 130, 140, 150]),
        ]
        result = analyze_layout(rows, 400, 600)
        self.assertEqual(result["column_count"], 2)
        self.assertEqual(result["lines"][0]["column"], 1)
        self.assertEqual(result["lines"][1]["column"], 2)

    def test_table_region_uses_table_bounds(self):
        result = analyze_layout(
            [line("خلية", [30, 100, 80, 120])], 200, 300,
            tables=[{"bbox": [10, 80, 190, 180]}],
        )
        self.assertEqual(result["lines"][0]["region"], "table")

    def test_invalid_boxes_are_skipped_without_crashing(self):
        result = analyze_layout([{"text": "bad", "bbox": [1, 2]}], 100, 100)
        self.assertEqual(result["lines"], [])
        self.assertEqual(result["direction"], "unknown")

    def test_footer_is_classified(self):
        result = analyze_layout([line("Page 4", [20, 550, 80, 570])], 200, 600)
        self.assertEqual(result["lines"][0]["region"], "footer")

    def test_table_detection_is_applied_to_existing_ocr_lines(self):
        original = {
            "image_width": 200,
            "image_height": 300,
            "engine": "tesseract",
            "engines": {"tesseract": {"available": True}},
            "lines": [line("قيمة", [30, 100, 80, 120]), line("عنوان", [20, 20, 90, 35])],
        }
        result = attach_table_regions(original, [{"bbox": [10, 80, 190, 180]}])
        self.assertEqual(result["lines"][0]["region"], "table")
        self.assertEqual(result["lines"][1]["region"], "header")
        self.assertEqual(result["layout"]["regions"]["table"], 1)
        self.assertEqual(result["engine"], "tesseract")
        self.assertEqual(result["engines"], original["engines"])
        self.assertNotIn("region", original["lines"][0])


if __name__ == "__main__":
    unittest.main()
