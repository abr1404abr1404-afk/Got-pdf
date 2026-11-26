import unittest
from unittest.mock import patch

import numpy as np
import main


class BoundedOcrTests(unittest.TestCase):
    @patch.object(main.pytesseract, "image_to_data", return_value={
        "text": [], "page_num": [], "block_num": [], "par_num": [],
        "line_num": [], "conf": [], "left": [], "top": [], "width": [], "height": [],
    })
    def test_tesseract_calls_engine_with_bounded_timeout(self, image_to_data):
        image = np.full((120, 240, 3), 255, dtype=np.uint8)
        rows, error = main._tesseract(image, "ara")
        self.assertEqual(rows, [])
        self.assertIsNone(error)
        self.assertEqual(
            image_to_data.call_args.kwargs["timeout"],
            main.TESSERACT_TIMEOUT_SECONDS,
        )

    def test_preprocess_downscales_oversized_images_to_configured_edge(self):
        image = np.full((3000, 2000, 3), 255, dtype=np.uint8)
        with patch.object(main, "OCR_MAX_IMAGE_EDGE", 1600), patch.object(main, "_deskew", side_effect=lambda value: value):
            result = main._preprocess(image)
        self.assertEqual(max(result.shape[:2]), min(1600, main.OCR_PREPROCESS_TARGET_EDGE))
        self.assertLess(result.shape[0] * result.shape[1], image.shape[0] * image.shape[1])

    @patch.object(main.pytesseract, "image_to_data")
    def test_timeout_retries_once_with_smaller_image_and_short_budget(self, image_to_data):
        image = np.full((1800, 1200, 3), 255, dtype=np.uint8)
        image_to_data.side_effect = [
            RuntimeError("Tesseract process timeout"),
            {
                "text": ["المجلس"], "page_num": [1], "block_num": [1],
                "par_num": [1], "line_num": [1], "conf": ["80"],
                "left": [10], "top": [10], "width": [100], "height": [25],
            },
        ]
        with patch.object(main, "TESSERACT_RETRY_MAX_EDGE", 900), patch.object(main, "TESSERACT_RETRY_TIMEOUT_SECONDS", 12):
            rows, error = main._tesseract(image, "ara")
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "المجلس")
        self.assertEqual(image_to_data.call_count, 2)
        self.assertEqual(image_to_data.call_args.kwargs["timeout"], 12)
        self.assertEqual(max(image_to_data.call_args.args[0].shape[:2]), 900)

    @patch.object(main.pytesseract, "image_to_data", side_effect=RuntimeError("Tesseract process timeout"))
    def test_retry_timeout_is_bounded_and_reported(self, image_to_data):
        image = np.full((1800, 1200, 3), 255, dtype=np.uint8)
        with patch.object(main, "TESSERACT_RETRY_MAX_EDGE", 900), patch.object(main, "TESSERACT_RETRY_TIMEOUT_SECONDS", 12):
            rows, error = main._tesseract(image, "ara")
        self.assertEqual(rows, [])
        self.assertIn("reduced-resolution retry failed", error)
        self.assertEqual(image_to_data.call_count, 2)


if __name__ == "__main__":
    unittest.main()
