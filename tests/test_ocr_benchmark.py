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
        self.assertAlmostEqual(error_rate("هذا كتاب مفيد", "هذا مفيد"), 1 / 3)

    def test_empty_reference(self):
        self.assertEqual(error_rate("", ""), 0)
        self.assertEqual(error_rate("", "نص"), 1)

    def test_invalid_metric_unit(self):
        with self.assertRaises(ValueError):
            error_rate("a", "b", "lines")


if __name__ == "__main__":
    unittest.main()
