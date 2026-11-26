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


if __name__ == "__main__":
    unittest.main()
