import unittest
from unittest.mock import patch

import numpy as np
import main


class TesseractTiledRecoveryTests(unittest.TestCase):
    def test_tall_image_is_split_and_boxes_are_mapped_to_source_coordinates(self):
        image = np.zeros((900, 300, 3), dtype=np.uint8)
        row = {
            "text": "اختبار",
            "confidence": 75.0,
            "bbox": [20, 20, 120, 60],
            "words": [{"text": "اختبار", "confidence": 75.0, "bbox": [20, 20, 120, 60]}],
            "engine": "tesseract",
        }
        with patch.object(main, "_tesseract", return_value=([dict(row)], None)) as recognize:
            rows, error = main._tesseract_tiled(image, "ara")
        self.assertIsNone(error)
        self.assertEqual(recognize.call_count, 3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["bbox"], [10, 10, 60, 30])
        self.assertEqual(rows[1]["bbox"], [10, 280, 60, 300])
        self.assertEqual(rows[2]["bbox"], [10, 580, 60, 600])
        self.assertEqual(rows[2]["words"][0]["bbox"], [10, 580, 60, 600])
        self.assertEqual(rows[0]["recovery_pass"], "tiled")

    def test_landscape_image_skips_tiled_recovery(self):
        image = np.zeros((300, 900, 3), dtype=np.uint8)
        with patch.object(main, "_tesseract") as recognize:
            rows, error = main._tesseract_tiled(image, "ara")
        self.assertEqual(rows, [])
        self.assertIsNone(error)
        recognize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
