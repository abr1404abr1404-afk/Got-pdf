import base64
import unittest

from paddle_vl_client import PaddleVLError, normalize_paddle_vl_response


class PaddleVLClientTests(unittest.TestCase):
    def test_normalizes_structured_arabic_document_pages(self):
        payload = {
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
                        "markdown": {"text": "| عمود | قيمة |"},
                    },
                ]
            },
        }
        parsed, docx = normalize_paddle_vl_response(payload)
        self.assertEqual(parsed["engine"], "PaddleOCR-VL-1.6")
        self.assertEqual(parsed["page_count"], 2)
        self.assertEqual(parsed["pages"][0]["page"], 1)
        self.assertIn("نص عربي", parsed["markdown"])
        self.assertIsNone(docx)

    def test_extracts_valid_docx_export(self):
        docx_bytes = b"PK\x03\x04test"
        payload = {
            "errorCode": 0,
            "result": {
                "layoutParsingResults": [{
                    "prunedResult": {},
                    "markdown": {"text": "نص"},
                    "exports": {"docx": {"content": base64.b64encode(docx_bytes).decode("ascii")}},
                }]
            },
        }
        parsed, output = normalize_paddle_vl_response(payload, export_docx=True)
        self.assertEqual(output, docx_bytes)
        self.assertEqual(parsed["page_count"], 1)

    def test_rejects_missing_docx_export(self):
        payload = {"errorCode": 0, "result": {"layoutParsingResults": [{"prunedResult": {}, "markdown": {"text": "نص"}}]}}
        with self.assertRaisesRegex(PaddleVLError, "ملف Word صالح"):
            normalize_paddle_vl_response(payload, export_docx=True)

    def test_rejects_service_error(self):
        with self.assertRaisesRegex(PaddleVLError, "خدمة التحليل"):
            normalize_paddle_vl_response({"errorCode": 500, "errorMsg": "خدمة التحليل فشلت"})

    def test_rejects_empty_or_invalid_result(self):
        with self.assertRaises(PaddleVLError):
            normalize_paddle_vl_response({"errorCode": 0, "result": {"layoutParsingResults": []}})


if __name__ == "__main__":
    unittest.main()
