import base64
import io
import unittest

from docx import Document

from paddle_vl_client import (
    PaddleVLError,
    markdown_pages_to_docx,
    normalize_paddle_vl_response,
)


class PaddleVLClientTests(unittest.TestCase):
    def payload(self):
        return {
            "logId": "request-123",
            "errorCode": 0,
            "result": {
                "layoutParsingResults": [
                    {
                        "prunedResult": {"parsing_res_list": [{"block_label": "text"}]},
                        "markdown": {"text": "# عنوان\n\nنص عربي"},
                    },
                    {
                        "prunedResult": {"parsing_res_list": []},
                        "markdown": {"text": "| عمود | قيمة |\n|---|---|\n| الاسم | أحمد |"},
                    },
                ]
            },
        }

    def test_normalizes_structured_arabic_document_pages(self):
        parsed, docx = normalize_paddle_vl_response(self.payload())
        self.assertEqual(parsed["engine"], "PaddleOCR-VL-1.6")
        self.assertEqual(parsed["page_count"], 2)
        self.assertEqual(parsed["pages"][0]["page"], 1)
        self.assertIn("نص عربي", parsed["markdown"])
        self.assertIsNone(docx)

    def test_prefers_native_paddle_vl_docx_export(self):
        payload = self.payload()
        native_docx = b"PK\\x03\\x04native-docx"
        payload["result"]["layoutParsingResults"][0]["exports"] = {
            "docx": {"content": base64.b64encode(native_docx).decode("ascii")}
        }
        parsed, output = normalize_paddle_vl_response(payload, export_docx=True)
        self.assertEqual(output, native_docx)
        self.assertEqual(parsed["page_count"], 2)

    def test_falls_back_to_editable_rtl_docx_from_markdown(self):
        parsed, output = normalize_paddle_vl_response(self.payload(), export_docx=True)
        self.assertTrue(output.startswith(b"PK"))
        doc = Document(io.BytesIO(output))
        self.assertIn("عنوان", "\n".join(p.text for p in doc.paragraphs))
        self.assertEqual(len(doc.tables), 1)
        self.assertEqual(doc.tables[0].cell(1, 1).text, "أحمد")
        arabic_paragraph = next(p for p in doc.paragraphs if "عنوان" in p.text)
        self.assertIsNotNone(arabic_paragraph._p.pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}bidi"))

    def test_rejects_invalid_native_docx_export(self):
        payload = self.payload()
        payload["result"]["layoutParsingResults"][0]["exports"] = {
            "docx": {"content": "not-base64!"}
        }
        with self.assertRaises(PaddleVLError):
            normalize_paddle_vl_response(payload, export_docx=True)

    def test_rejects_service_error(self):
        with self.assertRaisesRegex(PaddleVLError, "خدمة التحليل"):
            normalize_paddle_vl_response({"errorCode": 500, "errorMsg": "خدمة التحليل فشلت"})

    def test_rejects_empty_or_invalid_result(self):
        with self.assertRaises(PaddleVLError):
            normalize_paddle_vl_response({"errorCode": 0, "result": {"layoutParsingResults": []}})

    def test_rejects_empty_docx_page_list(self):
        with self.assertRaises(PaddleVLError):
            markdown_pages_to_docx([])


if __name__ == "__main__":
    unittest.main()
