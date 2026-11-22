import ast
import pathlib
import unittest

SOURCE = pathlib.Path("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
FUNCTION = next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "_reading_order")
MODULE = ast.Module(body=[FUNCTION], type_ignores=[])
ast.fix_missing_locations(MODULE)
NAMESPACE = {}
exec(compile(MODULE, "main.py", "exec"), NAMESPACE)
reading_order = NAMESPACE["_reading_order"]


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

    def test_lines_are_ordered_top_to_bottom(self):
        rows = [row("السطر الثاني", 10, 60, 100, 80), row("السطر الأول", 10, 10, 100, 30)]
        result = reading_order(rows)
        self.assertEqual([item["text"] for item in result], ["السطر الأول", "السطر الثاني"])

    def test_empty_and_single_line_inputs(self):
        self.assertEqual(reading_order([]), [])
        item = row("اختبار", 0, 0, 40, 20)
        self.assertEqual(reading_order([item]), [item])



class OcrModeTests(unittest.TestCase):
    def run_mode(self, mode):
        main_tree = ast.parse(SOURCE)
        hybrid = next(node for node in main_tree.body if isinstance(node, ast.FunctionDef) and node.name == "_hybrid")
        module = ast.Module(body=[hybrid], type_ignores=[])
        ast.fix_missing_locations(module)
        calls = []
        namespace = {
            "OCR_MODE": mode,
            "_preprocess": lambda image: image,
            "_paddle": lambda image, language: (calls.append("paddle") or [], None),
            "_tesseract": lambda image, language: (calls.append("tesseract") or [], None),
            "_dedupe": lambda rows: rows,
            "_reading_order": lambda rows: rows,
        }
        exec(compile(module, "main.py", "exec"), namespace)
        namespace["_hybrid"]("image", "ara+eng")
        return calls

    def test_hybrid_runs_both_engines(self):
        self.assertEqual(self.run_mode("hybrid"), ["paddle", "tesseract"])

    def test_paddle_mode_skips_tesseract(self):
        self.assertEqual(self.run_mode("paddleocr"), ["paddle"])

    def test_tesseract_mode_skips_paddle(self):
        self.assertEqual(self.run_mode("tesseract"), ["tesseract"])


if __name__ == "__main__":
    unittest.main()
