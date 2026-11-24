import unittest

from tools.ocr_benchmark import edit_distance, error_rate, normalize_text


class OcrBenchmarkMetricTests(unittest.TestCase):
    def test_arabic_marks_and_tatweel_are_ignored(self):
        self.assertEqual(normalize_text("السَّلَامـ"), "السلام")

    def test_unicode_compatibility_normalization(self):
        self.assertEqual(normalize_text("ＡＢＣ"), "abc")

    def test_edit_distance(self):
        self.assertEqual(edit_distance("kitten", "sitting"), 3)

    def test_character_error_rate(self):
        self.assertAlmostEqual(error_rate("كتاب", "كتا"), 0.25)

    def test_word_error_rate(self):
        self.assertAlmostEqual(error_rate("هذا كتاب مفيد", "هذا مفيد", "words"), 1 / 3)

    def test_empty_reference(self):
        self.assertEqual(error_rate("", ""), 0)
        self.assertEqual(error_rate("", "نص"), 1)

    def test_summary_reports_per_category(self):
        from tools.ocr_benchmark import summarize_results

        rows = [
            {"engine": "hybrid", "category": "decorative", "cer": 0.2, "wer": 0.3, "seconds": 1.0, "error": None},
            {"engine": "hybrid", "category": "printed", "cer": 0.1, "wer": 0.2, "seconds": 0.8, "error": None},
            {"engine": "tesseract", "category": "decorative", "cer": 0.4, "wer": 0.5, "seconds": 0.5, "error": "engine error"},
        ]
        overall, by_category = summarize_results(rows, ["hybrid", "tesseract"])
        self.assertEqual(overall[0]["samples"], 2)
        decorative = [row for row in by_category if row["category"] == "decorative"]
        self.assertEqual(len(decorative), 2)
        hybrid = next(row for row in decorative if row["engine"] == "hybrid")
        self.assertEqual(hybrid["successful_samples"], 1)
        self.assertAlmostEqual(hybrid["mean_cer"], 0.2)

    def test_invalid_metric_unit(self):
        with self.assertRaises(ValueError):
            error_rate("a", "b", "lines")


if __name__ == "__main__":
    unittest.main()
