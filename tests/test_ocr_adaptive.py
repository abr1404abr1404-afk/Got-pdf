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
    def test_weak_first_pass_uses_single_adaptive_fallback(self, tess, paddle, layout, style):
        weak = {"text": "المجلس", "confidence": 20.0, "bbox": [10, 10, 120, 40], "engine": "tesseract"}
        strong = {"text": "المجلس", "confidence": 72.0, "bbox": [10, 10, 120, 40], "engine": "tesseract"}
        tess.side_effect = [([weak], None), ([strong], None), ([strong], None)]
        layout.return_value = {"lines": [strong], "tables": [], "direction": "rtl"}
        with patch.object(main, "OCR_MODE", "tesseract"):
            result = main._hybrid(self.image, "ara")
        self.assertEqual(tess.call_count, 2)
        self.assertEqual(result["lines"][0]["text"], "المجلس")

    @patch.object(main, "analyze_text_style", return_value={"style_classification": "uncertain"})
    @patch.object(main, "analyze_layout")
    @patch.object(main, "_paddle", return_value=([], "disabled"))
    @patch.object(main, "_tesseract", return_value=([], "RuntimeError: Tesseract process timeout"))
    @patch.object(main, "_preprocess", side_effect=lambda image: image)
    def test_timeout_does_not_trigger_another_expensive_ocr_pass(self, preprocess, tess, paddle, layout, style):
        layout.return_value = {"lines": [], "direction": "unknown", "column_count": 1, "regions": {}}
        with patch.object(main, "OCR_MODE", "tesseract"):
            result = main._hybrid(self.image, "ara")
        self.assertEqual(tess.call_count, 1)
        self.assertEqual(result["engine"], "none")

    def test_preprocess_uses_cpu_bounded_target_edge(self):
        image = np.full((2200, 1600, 3), 255, dtype=np.uint8)
        with patch.object(main, "OCR_PREPROCESS_TARGET_EDGE", 1200), patch.object(main, "_deskew", side_effect=lambda value: value):
            prepared = main._preprocess(image)
        self.assertEqual(max(prepared.shape[:2]), 1200)
        self.assertEqual(prepared.ndim, 3)


if __name__ == "__main__":
    unittest.main()
