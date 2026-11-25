import io
import json
import unittest
import zipfile

import pymupdf

from pdf_batch import compress_pdf_batch


def sample_pdf(text="Batch test"):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


class PdfBatchTests(unittest.TestCase):
    def test_batch_creates_safe_unique_names_and_manifest(self):
        data = sample_pdf()
        archive, report = compress_pdf_batch(
            [("../same.pdf", data), ("same.pdf", data)],
            "lossless",
        )
        self.assertEqual(len(report), 2)
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            names = zipped.namelist()
            self.assertEqual(names[:2], ["same.pdf", "same-2.pdf"])
            self.assertNotIn("../same.pdf", names)
            manifest = json.loads(zipped.read("alfalqi-batch-report.json"))
            self.assertEqual(manifest["count"], 2)
            with pymupdf.open(stream=zipped.read("same.pdf"), filetype="pdf") as pdf:
                self.assertIn("Batch test", pdf[0].get_text())

    def test_empty_batch_rejected(self):
        with self.assertRaisesRegex(ValueError, "ملف PDF واحدًا"):
            compress_pdf_batch([])

    def test_too_many_files_rejected(self):
        with self.assertRaisesRegex(ValueError, "الحد الأقصى"):
            compress_pdf_batch([("x.pdf", b"x")] * 3, max_files=2)

    def test_per_file_limit_rejected(self):
        with self.assertRaisesRegex(ValueError, "حجم الملف"):
            compress_pdf_batch([("x.pdf", b"12345")], max_file_bytes=4)

    def test_total_limit_rejected(self):
        with self.assertRaisesRegex(ValueError, "إجمالي أحجام"):
            compress_pdf_batch([("a.pdf", b"12"), ("b.pdf", b"34")], max_total_bytes=3)

    def test_invalid_pdf_rejected(self):
        with self.assertRaises(ValueError):
            compress_pdf_batch([("bad.pdf", b"not a pdf")])

    def test_invalid_level_rejected(self):
        with self.assertRaisesRegex(ValueError, "مستوى الضغط"):
            compress_pdf_batch([("a.pdf", sample_pdf())], "ultra")


if __name__ == "__main__":
    unittest.main()
