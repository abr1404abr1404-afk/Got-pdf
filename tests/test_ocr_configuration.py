import unittest

import main


class OcrModeConfigurationTests(unittest.TestCase):
    def test_hybrid_is_disabled_without_explicit_paddle_opt_in(self):
        self.assertEqual(main._resolve_ocr_mode("hybrid", False), "tesseract")

    def test_paddle_only_is_disabled_without_explicit_opt_in(self):
        self.assertEqual(main._resolve_ocr_mode("paddleocr", False), "tesseract")

    def test_hybrid_is_available_with_explicit_opt_in(self):
        self.assertEqual(main._resolve_ocr_mode("hybrid", True), "hybrid")

    def test_paddle_alias_is_normalized(self):
        self.assertEqual(main._resolve_ocr_mode("paddle", True), "paddleocr")

    def test_invalid_mode_falls_back_to_tesseract(self):
        self.assertEqual(main._resolve_ocr_mode("unknown", True), "tesseract")


if __name__ == "__main__":
    unittest.main()
