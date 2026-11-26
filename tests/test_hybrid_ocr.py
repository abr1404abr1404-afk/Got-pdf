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
        with patch.object(main, "_paddle_runtime_available", return_value=True), patch.object(main, "OCR_MODE", "hybrid"):
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
        with patch.object(main, "_paddle_runtime_available", return_value=True), patch.object(main, "OCR_MODE", "hybrid"):
            result = main._hybrid(self.image, "ara")
        tesseract.assert_called_once()
        self.assertEqual(result["engine"], "hybrid")
        self.assertEqual(result["lines"][0]["text"], "المجلس")

    @patch.object(main, "analyze_text_style", return_value=None)
    @patch.object(main, "analyze_layout")
    @patch.object(main, "_tesseract", return_value=([{
        "text": "المجلس", "confidence": 82.0, "bbox": [10, 20, 150, 55],
        "engine": "tesseract",
    }], None))
    @patch.object(main, "_paddle", return_value=([{
        "text": "المجلس", "confidence": 90.0, "bbox": [10, 20, 150, 55],
        "engine": "paddleocr",
    }], None))
    @patch.object(main, "_preprocess", side_effect=lambda image: image)
    def test_explicit_tesseract_override_runs_even_when_paddle_is_confident(
        self, preprocess, paddle, tesseract, analyze_layout, style
    ):
        analyze_layout.return_value = {
            "lines": [{
                "text": "المجلس", "confidence": 82.0, "bbox": [10, 20, 150, 55],
                "engine": "tesseract",
            }], "direction": "rtl"
        }
        with patch.object(main, "OCR_MODE", "hybrid"):
            result = main._hybrid(self.image, "ara", "tesseract")
        tesseract.assert_called_once()
        paddle.assert_not_called()
        self.assertEqual(result["engine"], "tesseract")


    def test_hybrid_without_paddle_uses_tesseract_fallback(self):
        tess_row = dict(self.row, engine="tesseract")
        with patch.object(main, "_preprocess", return_value=self.image), \
             patch.object(main, "_paddle") as paddle, \
             patch.object(main, "_tesseract", return_value=([tess_row], None)) as tesseract, \
             patch.object(main, "analyze_layout", return_value={"lines": [tess_row], "direction": "rtl"}), \
             patch.object(main, "analyze_text_style", return_value=None), \
             patch.object(main, "_paddle_runtime_available", return_value=False), \
             patch.object(main, "OCR_MODE", "hybrid"):
            result = main._hybrid(self.image, "ara")
        paddle.assert_not_called()
        tesseract.assert_called_once()
        self.assertEqual(result["engine"], "tesseract")

    def test_explicit_paddle_override_requires_opt_in(self):
        with patch.object(main, "PADDLE_OCR_OPT_IN", False):
            with self.assertRaises(ValueError):
                main._hybrid(self.image, "ara", "paddleocr")


if __name__ == "__main__":
    unittest.main()
