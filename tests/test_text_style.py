import unittest

import cv2
import numpy as np

from text_style import analyze_text_style


class TextStyleTests(unittest.TestCase):
    def test_detects_colored_ink_and_light_background(self):
        image = np.full((100, 240, 3), 245, dtype=np.uint8)
        cv2.putText(image, "TEST", (20, 68), cv2.FONT_HERSHEY_SIMPLEX, 1.5,
                    (20, 40, 180), 3, cv2.LINE_AA)
        style = analyze_text_style(image, [15, 30, 145, 75], text="TEST")
        self.assertRegex(style["ink_color"], r"^#[0-9a-f]{6}$")
        self.assertRegex(style["background_color"], r"^#[0-9a-f]{6}$")
        self.assertGreater(style["contrast"], 50)
        self.assertIn("handwriting_candidate", style)
        self.assertEqual(style["analysis"], "visual_heuristic")
        self.assertEqual(style["script_hint"], "latin")
        self.assertGreater(style["estimated_stroke_width_px"], 0)
        self.assertGreaterEqual(style["baseline_ratio"], 0)
        self.assertIn(style["style_classification"], {
            "uncertain", "handwriting_possible", "decorative_or_irregular", "printed_or_regular"
        })

    def test_recommends_flat_fill_for_uniform_page(self):
        image = np.full((100, 240, 3), 250, dtype=np.uint8)
        cv2.putText(image, "TEST", (20, 68), cv2.FONT_HERSHEY_SIMPLEX, 1.5,
                    (0, 0, 0), 3, cv2.LINE_AA)
        style = analyze_text_style(image, [15, 30, 145, 75], text="TEST")
        self.assertEqual(style["background_complexity"], "flat")
        self.assertEqual(style["recommended_cleanup"], "sampled_solid_fill")
        self.assertGreaterEqual(style["background_analysis_confidence"], 0.1)

    def test_flags_textured_background_for_preview(self):
        image = np.full((100, 240, 3), 245, dtype=np.uint8)
        for y in range(0, 100, 4):
            image[y:y + 2, :, :] = 210
        cv2.putText(image, "TEST", (20, 68), cv2.FONT_HERSHEY_SIMPLEX, 1.5,
                    (0, 0, 0), 3, cv2.LINE_AA)
        style = analyze_text_style(image, [15, 30, 145, 75], text="TEST")
        self.assertIn(style["background_complexity"], {"light_texture", "complex"})
        self.assertIn(style["recommended_cleanup"], {"inpaint_preview", "manual_review"})

    def test_detects_arabic_script_hint(self):
        image = np.full((80, 180, 3), 255, dtype=np.uint8)
        cv2.putText(image, "ARABIC", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                    (0, 0, 0), 2, cv2.LINE_AA)
        style = analyze_text_style(image, [5, 15, 150, 65], text="مرحبا بالعالم")
        self.assertEqual(style["script_hint"], "arabic")

    def test_rejects_invalid_regions(self):
        image = np.full((20, 20, 3), 255, dtype=np.uint8)
        with self.assertRaises(ValueError):
            analyze_text_style(image, [1, 1, 1, 5])
        with self.assertRaises(ValueError):
            analyze_text_style(image, [1, 1, 5])


if __name__ == "__main__":
    unittest.main()
