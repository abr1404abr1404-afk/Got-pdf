import unittest
from unittest.mock import patch

import numpy as np
import main


class HybridOcrSelectionTests(unittest.TestCase):
    def setUp(self):
        self.image = np.full((240, 320, 3), 255, dtype=np.uint8)
        self.row = {
            "text": "المجلس",
            "confidence": 86.0,
            "bbox": [10, 20, 150, 55],
            "engine": "paddleocr",
        }

    @patch.object(main, "analyze_text_style", return_value=None)
    @patch.object(main, "analyze_layout")
    @patch.object(main, "_tesseract")
    @patch.object(main, "_paddle", return_value=([{
        "text": "المجلس", "confidence": 86.0, "bbox": [10, 20, 150, 55],
        "engine": "paddleocr",
    }], None))
    @patch.object(main, "_preprocess", side_effect=lambda image: image)
    def test_confident_paddle_result_skips_expensive_tesseract(
        self, preprocess, paddle, tesseract, analyze_layout, style
    ):
        analyze_layout.return_value = {
            "lines": [dict(self.row)], "direction": "rtl"
        }
        with patch.object(main, "OCR_MODE", "hybrid"):
            result = main._hybrid(self.image, "ara")
        tesseract.assert_not_called()
        self.assertEqual(result["engine"], "paddleocr")
        self.assertEqual(result["lines"][0]["text"], "المجلس")

    @patch.object(main, "analyze_text_style", return_value=None)
    @patch.object(main, "analyze_layout")
    @patch.object(main, "_tesseract", return_value=([{
        "text": "المجلس", "confidence": 82.0, "bbox": [10, 20, 150, 55],
        "engine": "tesseract",
    }], None))
    @patch.object(main, "_paddle", return_value=([{
        "text": "المجلس", "confidence": 22.0, "bbox": [10, 20, 150, 55],
        "engine": "paddleocr",
    }], None))
    @patch.object(main, "_preprocess", side_effect=lambda image: image)
    def test_weak_paddle_result_falls_back_to_tesseract(
        self, preprocess, paddle, tesseract, analyze_layout, style
    ):
        analyze_layout.return_value = {
            "lines": [{
                "text": "المجلس", "confidence": 82.0, "bbox": [10, 20, 150, 55],
                "engine": "tesseract",
            }], "direction": "rtl"
        }
        with patch.object(main, "OCR_MODE", "hybrid"):
            result = main._hybrid(self.image, "ara")
        tesseract.assert_called_once()
        self.assertEqual(result["engine"], "hybrid")
        self.assertEqual(result["lines"][0]["text"], "المجلس")


if __name__ == "__main__":
    unittest.main()
