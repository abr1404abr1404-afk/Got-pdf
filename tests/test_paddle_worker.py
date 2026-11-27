import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "paddle-worker"))
import app as paddle_worker


class PaddleWorkerContractTests(unittest.TestCase):
    def setUp(self):
        self.old_key = paddle_worker.APP_KEY
        paddle_worker.APP_KEY = "test-worker-secret"
        self.client = TestClient(paddle_worker.app)

    def tearDown(self):
        paddle_worker.APP_KEY = self.old_key

    @staticmethod
    def png_bytes():
        image = Image.new("RGB", (480, 180), "white")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        return stream.getvalue()

    def test_health_does_not_claim_model_loaded(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIn("model_loaded", response.json())

    def test_rejects_missing_bearer_token(self):
        response = self.client.post(
            "/api/ocr/image",
            files={"file": ("test.png", self.png_bytes(), "image/png")},
            data={"language": "ara+eng"},
        )
        self.assertEqual(response.status_code, 401)

    def test_returns_got_pdf_compatible_ocr_contract(self):
        fixture = [{
            "text": "اختبار OCR",
            "confidence": 96.5,
            "bbox": [20, 30, 220, 80],
            "engine": "paddleocr-pp-ocrv5-ar",
        }]
        with patch.object(paddle_worker, "_recognize", return_value=fixture):
            response = self.client.post(
                "/api/ocr/image",
                headers={"Authorization": "Bearer test-worker-secret"},
                files={"file": ("test.png", self.png_bytes(), "image/png")},
                data={"language": "ara+eng"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["image_width"], 480)
        self.assertEqual(payload["image_height"], 180)
        self.assertEqual(payload["lines"][0]["text"], "اختبار OCR")
        self.assertEqual(payload["lines"][0]["bbox"], [20, 30, 220, 80])
        self.assertEqual(payload["tables"], [])

    def test_rejects_unsupported_language(self):
        response = self.client.post(
            "/api/ocr/image",
            headers={"Authorization": "Bearer test-worker-secret"},
            files={"file": ("test.png", self.png_bytes(), "image/png")},
            data={"language": "fra"},
        )
        self.assertEqual(response.status_code, 422)

    def test_normalizes_paddle_result_boxes_and_scores(self):
        item = SimpleNamespace(json={
            "res": {
                "rec_texts": ["مرحبا"],
                "rec_scores": [0.91],
                "rec_boxes": [[10, 20, 180, 70]],
            }
        })
        rows = paddle_worker._rows_from_result([item])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bbox"], [10, 20, 180, 70])
        self.assertAlmostEqual(rows[0]["confidence"], 91.0)


if __name__ == "__main__":
    unittest.main()
