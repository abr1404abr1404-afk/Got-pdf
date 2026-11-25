import ast
import pathlib
import unittest
import unicodedata

SOURCE = pathlib.Path("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
FUNCTIONS = [node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name in {"_reading_order", "_bidi_order"}]
MODULE = ast.Module(body=FUNCTIONS, type_ignores=[])
ast.fix_missing_locations(MODULE)
NAMESPACE = {"unicodedata": unicodedata}
exec(compile(MODULE, "main.py", "exec"), NAMESPACE)
reading_order = NAMESPACE["_reading_order"]
bidi_order = NAMESPACE["_bidi_order"]


def row(text, x0, y0, x1, y1):
    return {"text": text, "bbox": [x0, y0, x1, y1]}


class ReadingOrderTests(unittest.TestCase):
    def test_arabic_line_is_right_to_left(self):
        rows = [row("الثاني", 10, 10, 80, 30), row("الأول", 100, 10, 170, 30)]
        result = reading_order(rows)
        self.assertEqual([item["text"] for item in result], ["الأول", "الثاني"])

    def test_english_line_is_left_to_right(self):
        rows = [row("world", 100, 10, 160, 30), row("Hello", 10, 10, 70, 30)]
        result = reading_order(rows)
        self.assertEqual([item["text"] for item in result], ["Hello", "world"])

    def test_mixed_arabic_line_preserves_latin_phrase_order(self):
        rows = [
            row("كلمة عربية", 10, 10, 45, 30),
            row("Hello", 50, 10, 90, 30),
            row("world", 95, 10, 135, 30),
            row("كلمة ثانية", 145, 10, 190, 30),
        ]
        result = reading_order(rows)
        self.assertEqual(
            [item["text"] for item in result],
            ["كلمة ثانية", "Hello", "world", "كلمة عربية"],
        )
    def test_arabic_line_keeps_numeric_run_left_to_right(self):
        rows = [
            row("الثاني", 10, 10, 55, 30),
            row("123", 60, 10, 85, 30),
            row("الأول", 90, 10, 135, 30),
        ]
        result = reading_order(rows)
        self.assertEqual([item["text"] for item in result], ["الأول", "123", "الثاني"])

    def test_neutral_punctuation_inherits_arabic_line_direction(self):
        rows = [
            row("الثاني", 10, 10, 55, 30),
            row("،", 60, 10, 65, 30),
            row("الأول", 70, 10, 115, 30),
        ]
        result = reading_order(rows)
        self.assertEqual([item["text"] for item in result], ["الأول", "،", "الثاني"])
    def test_unicode_arabic_extended_letters_are_rtl(self):
        rows = [row("\u08a1", 10, 10, 40, 30), row("\u08a0", 50, 10, 80, 30)]
        result = reading_order(rows)
        self.assertEqual([item["text"] for item in result], ["\u08a0", "\u08a1"])
    def test_line_edges_determine_arabic_base_direction_when_latin_is_longer(self):
        rows = [
            row("ك", 10, 10, 20, 30),
            row("Hello", 30, 10, 65, 30),
            row("wonderful", 70, 10, 125, 30),
            row("world", 130, 10, 165, 30),
            row("م", 170, 10, 180, 30),
        ]
        result = reading_order(rows)
        self.assertEqual([item["text"] for item in result], [
            "م", "Hello", "wonderful", "world", "ك"
        ])
    def test_mixed_arabic_word_boxes_preserve_latin_phrase_order(self):
        words = [
            (10, 10, 35, 25, 95, "كلمة عربية"),
            (45, 10, 75, 25, 95, "Hello"),
            (80, 10, 110, 25, 95, "world"),
            (120, 10, 155, 25, 95, "كلمة ثانية"),
        ]
        result = bidi_order(words, lambda item: item[5], lambda item: item[0])
        self.assertEqual([item[5] for item in result], [
            "كلمة ثانية", "Hello", "world", "كلمة عربية"
        ])
    def test_arabic_two_column_page_reads_right_column_first(self):
        rows = [
            row("يسار أعلى", 10, 10, 100, 30),
            row("يسار أسفل", 10, 60, 100, 80),
            row("يمين أعلى", 250, 10, 340, 30),
            row("يمين أسفل", 250, 60, 340, 80),
        ]
        result = reading_order(rows)
        self.assertEqual([item["text"] for item in result], [
            "يمين أعلى", "يمين أسفل", "يسار أعلى", "يسار أسفل"
        ])

    def test_english_two_column_page_reads_left_column_first(self):
        rows = [
            row("Left top", 10, 10, 100, 30),
            row("Left bottom", 10, 60, 100, 80),
            row("Right top", 250, 10, 340, 30),
            row("Right bottom", 250, 60, 340, 80),
        ]
        result = reading_order(rows)
        self.assertEqual([item["text"] for item in result], [
            "Left top", "Left bottom", "Right top", "Right bottom"
        ])
    def test_spanning_title_is_not_dropped_when_columns_are_ambiguous(self):
        rows = [
            row("عنوان الصفحة", 10, 0, 340, 18),
            row("يسار أعلى", 10, 30, 100, 50),
            row("يسار أسفل", 10, 70, 100, 90),
            row("يمين أعلى", 250, 30, 340, 50),
            row("يمين أسفل", 250, 70, 340, 90),
        ]
        result = reading_order(rows)
        self.assertEqual(len(result), len(rows))
        self.assertCountEqual([item["text"] for item in result], [item["text"] for item in rows])
    def test_lines_are_ordered_top_to_bottom(self):
        rows = [row("السطر الثاني", 10, 60, 100, 80), row("السطر الأول", 10, 10, 100, 30)]
        result = reading_order(rows)
        self.assertEqual([item["text"] for item in result], ["السطر الأول", "السطر الثاني"])

    def test_empty_and_single_line_inputs(self):
        self.assertEqual(reading_order([]), [])
        item = row("اختبار", 0, 0, 40, 20)
        self.assertEqual(reading_order([item]), [item])



TABLE_TREE = ast.parse(SOURCE)
TABLE_FUNCTIONS = [
    node for node in TABLE_TREE.body
    if isinstance(node, ast.FunctionDef) and node.name in {"_group_positions", "_table_from_grid", "_normalize_line_angle", "_adaptive_threshold_block_size"}
]
TABLE_MODULE = ast.Module(body=TABLE_FUNCTIONS, type_ignores=[])
ast.fix_missing_locations(TABLE_MODULE)
TABLE_NAMESPACE = {}
exec(compile(TABLE_MODULE, "main.py", "exec"), TABLE_NAMESPACE)
group_positions = TABLE_NAMESPACE["_group_positions"]
table_from_grid = TABLE_NAMESPACE["_table_from_grid"]
normalize_line_angle = TABLE_NAMESPACE["_normalize_line_angle"]
adaptive_threshold_block_size = TABLE_NAMESPACE["_adaptive_threshold_block_size"]


class TableExtractionTests(unittest.TestCase):
    def test_group_positions_collapses_thick_rules(self):
        self.assertEqual(group_positions([10, 11, 12, 40, 41, 90]), [11, 40, 90])

    def test_arabic_table_cells_are_returned_right_to_left(self):
        lines = [
            {"text": "يمين", "bbox": [120, 10, 180, 30]},
            {"text": "يسار", "bbox": [20, 10, 80, 30]},
            {"text": "قيمة", "bbox": [20, 60, 80, 80]},
        ]
        table = table_from_grid([0, 0, 200, 100], [0, 100, 200], [0, 50, 100], lines)
        self.assertEqual(table["direction"], "rtl")
        self.assertEqual(table["rows"], [["يمين", "يسار"], ["", "قيمة"]])
        self.assertEqual(table["row_count"], 2)
        self.assertEqual(table["column_count"], 2)

    def test_english_table_cells_are_left_to_right(self):
        lines = [
            {"text": "Name", "bbox": [10, 10, 80, 30]},
            {"text": "Score", "bbox": [120, 10, 180, 30]},
        ]
        table = table_from_grid([0, 0, 200, 100], [0, 100, 200], [0, 50, 100], lines)
        self.assertEqual(table["direction"], "ltr")
        self.assertEqual(table["rows"][0], ["Name", "Score"])

    def test_grid_without_enough_rows_or_columns_is_ignored(self):
        self.assertIsNone(table_from_grid([0, 0, 100, 100], [0, 100], [0, 50, 100], []))


class ImagePreprocessingSafetyTests(unittest.TestCase):
    def test_angle_normalization_uses_shortest_orientation(self):
        self.assertEqual(normalize_line_angle(179), -1)
        self.assertEqual(normalize_line_angle(-179), 1)
        self.assertEqual(normalize_line_angle(8), 8)

    def test_tiny_images_skip_adaptive_table_threshold(self):
        self.assertIsNone(adaptive_threshold_block_size(20, 200))
        self.assertIsNone(adaptive_threshold_block_size(200, 30))

    def test_normal_images_use_valid_odd_threshold_block(self):
        self.assertEqual(adaptive_threshold_block_size(31, 31), 31)
        self.assertEqual(adaptive_threshold_block_size(1200, 800), 31)


class OcrModeTests(unittest.TestCase):
    def run_mode(self, mode):
        main_tree = ast.parse(SOURCE)
        hybrid = next(node for node in main_tree.body if isinstance(node, ast.FunctionDef) and node.name == "_hybrid")
        module = ast.Module(body=[hybrid], type_ignores=[])
        ast.fix_missing_locations(module)
        calls = []
        namespace = {
            "np": type("NumpyStub", (), {"ndarray": object}),
            "OCR_MODE": mode,
            "_preprocess": lambda image: image,
            "cv2": type("CV2Stub", (), {"COLOR_BGR2GRAY": 1, "COLOR_GRAY2BGR": 2, "ADAPTIVE_THRESH_GAUSSIAN_C": 3, "THRESH_BINARY": 4, "THRESH_OTSU": 5, "cvtColor": staticmethod(lambda image, code: image), "adaptiveThreshold": staticmethod(lambda image, *args: image), "threshold": staticmethod(lambda image, *args: (0, image))})(),
            "_paddle": lambda image, language: (calls.append("paddle") or [], None),
            "_tesseract": lambda image, language, psm=11: (calls.append("tesseract") or [], None),
            "_dedupe": lambda rows: rows,
            "_reading_order": lambda rows: rows,
        }
        exec(compile(module, "main.py", "exec"), namespace)
        image = type("ImageStub", (), {"shape": (100, 200, 3)})()
        namespace["_hybrid"](image, "ara+eng")
        return calls

    def test_hybrid_runs_both_engines(self):
        self.assertEqual(self.run_mode("hybrid"), ["paddle", "tesseract", "tesseract", "tesseract"])

    def test_paddle_mode_skips_tesseract(self):
        self.assertEqual(self.run_mode("paddleocr"), ["paddle"])

    def test_tesseract_mode_skips_paddle(self):
        self.assertEqual(self.run_mode("tesseract"), ["tesseract", "tesseract", "tesseract"])


if __name__ == "__main__":
    unittest.main()
