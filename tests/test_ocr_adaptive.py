import unittest
from unittest.mock import patch

import numpy as np
import main


class AdaptiveOcrPassTests(unittest.TestCase):
    def setUp(self):
        self.image = np.full((120, 240, 3), 255, dtype=np.uint8)

    @patch.object(main, "analyze_text_style", return_value={"style_classification": "printed_or_regular"})
    @patch.object(main, "analyze_layout")
    @patch.object(main, "_paddle", return_value=([], "disabled"))
    @patch.object(main, "_tesseract")
    def test_good_first_pass_skips_expensive_variants(self, tess, paddle, layout, style):
        line = {"text": "المجلس", "confidence": 82.0, "bbox": [10, 10, 120, 40], "engine": "tesseract"}
        tess.return_value = ([line], None)
        layout.return_value = {"lines": [line], "tables": [], "direction": "rtl"}
        with patch.object(main, "OCR_MODE", "tesseract"):
            result = main._hybrid(self.image, "ara")
        self.assertEqual(tess.call_count, 1)
        self.assertEqual(result["lines"][0]["text"], "المجلس")

    @patch.object(main, "analyze_text_style", return_value={"style_classification": "uncertain"})
    @patch.object(main, "analyze_layout")
    @patch.object(main, "_paddle", return_value=([], "disabled"))
    @patch.object(main, "_tesseract")
    def test_weak_first_pass_uses_adaptive_and_inverted_fallbacks(self, tess, paddle, preprocess, layout, style):
        weak = {"text": "المجلس", "confidence": 20.0, "bbox": [10, 10, 120, 40], "engine": "tesseract"}
        strong = {"text": "المجلس", "confidence": 72.0, "bbox": [10, 10, 120, 40], "engine": "tesseract"}
        tess.side_effect = [([weak], None), ([strong], None), ([strong], None)]
        layout.return_value = {"lines": [strong], "tables": [], "direction": "rtl"}
        with patch.object(main, "OCR_MODE", "tesseract"):
            result = main._hybrid(self.image, "ara")
        self.assertEqual(tess.call_count, 3)
        self.assertEqual(result["lines"][0]["text"], "المجلس")


if __name__ == "__main__":
    unittest.main()
