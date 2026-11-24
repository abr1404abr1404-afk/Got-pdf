"""Tests for safe, bounded page-by-page PDF comparison."""
import unittest

import pymupdf

from pdf_compare import compare_pdf_bytes


def make_pdf(lines):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 500, 700), "\\n".join(lines), fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


class PdfCompareTests(unittest.TestCase):
    def test_reports_added_and_removed_text_without_changing_source(self):
        original = make_pdf(["Alpha", "Keep"])
        revised = make_pdf(["Beta", "Keep", "New"])

        result = compare_pdf_bytes(original, revised)

        self.assertEqual(result["changed_pages"], 1)
        self.assertEqual(result["pages"][0]["status"], "changed")
        self.assertIn("Beta", result["pages"][0]["text"]["added_lines"])
        self.assertIn("Alpha", result["pages"][0]["text"]["removed_lines"])
        self.assertIn("New", result["pages"][0]["text"]["added_lines"])
        self.assertEqual(make_pdf(["Alpha", "Keep"]), original)

    def test_detects_added_pages(self):
        one_page = make_pdf(["Page one"])
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "Page one")
        doc.new_page().insert_text((72, 72), "Page two")
        two_pages = doc.tobytes()
        doc.close()

        result = compare_pdf_bytes(one_page, two_pages)

        self.assertEqual(result["revised_page_count"], 2)
        self.assertEqual(result["changed_pages"], 1)
        self.assertEqual(result["pages"][1]["status"], "added")

    def test_rejects_empty_and_invalid_pdfs(self):
        valid = make_pdf(["valid"])
        for bad in (b"", b"not pdf"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    compare_pdf_bytes(bad, valid)
                with self.assertRaises(ValueError):
                    compare_pdf_bytes(valid, bad)


if __name__ == "__main__":
    unittest.main()
