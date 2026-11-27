"""Contract tests for optional integrations when external services are not configured.

These tests make no paid API calls and never require real provider credentials.
"""
import unittest
from unittest.mock import patch

import httpx
import main


class OptionalIntegrationReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_health_distinguishes_configuration_from_verification(self):
        with (
            patch.object(main, "OPENAI_API_KEY", ""),
            patch.object(main, "GOTENBERG_URL", ""),
            patch.object(main, "PADDLEOCR_VL_URL", ""),
        ):
            response = await self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["ai_status"], "not_configured")
        self.assertEqual(payload["office_conversion_status"], "not_configured")
        self.assertEqual(payload["paddleocr_vl_status"], "not_configured")
        capabilities = payload["capabilities"]
        for key in ("assistant.chat", "assistant.extract",
                    "convert.office_to_pdf", "document.parse"):
            with self.subTest(capability=key):
                self.assertFalse(capabilities[key]["configured"])
                self.assertFalse(capabilities[key]["verified"])
                self.assertEqual(capabilities[key]["status"], "not_configured")

    async def test_configured_integrations_are_not_mislabeled_as_verified(self):
        with (
            patch.object(main, "OPENAI_API_KEY", "test-only-not-a-real-key"),
            patch.object(main, "GOTENBERG_URL", "http://gotenberg.invalid"),
            patch.object(main, "PADDLEOCR_VL_URL", "http://paddle-vl.invalid"),
        ):
            response = await self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["ai_status"], "configured_unverified")
        self.assertEqual(payload["office_conversion_status"], "configured_unverified")
        self.assertEqual(payload["paddleocr_vl_status"], "configured_unverified")
        for key in ("assistant.chat", "assistant.extract",
                    "convert.office_to_pdf", "document.parse"):
            with self.subTest(capability=key):
                self.assertTrue(payload["capabilities"][key]["configured"])
                self.assertFalse(payload["capabilities"][key]["verified"])
                self.assertEqual(payload["capabilities"][key]["status"], "configured_unverified")

    async def test_ai_routes_fail_cleanly_without_credentials(self):
        with patch.object(main, "OPENAI_API_KEY", ""):
            chat = await self.client.post("/api/assistant/chat", json={
                "document_text": "صفحة 1: نص تجريبي",
                "question": "لخص النص",
            })
            extract = await self.client.post("/api/assistant/extract", json={
                "document_text": "صفحة 1: نص تجريبي",
            })
        self.assertEqual(chat.status_code, 503)
        self.assertEqual(extract.status_code, 503)

    async def test_office_conversion_fails_cleanly_without_gotenberg(self):
        with patch.object(main, "GOTENBERG_URL", ""):
            response = await self.client.post(
                "/api/convert/office-to-pdf",
                files={"file": ("sample.docx", b"synthetic-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )
        self.assertEqual(response.status_code, 503)

    async def test_advanced_parse_fails_cleanly_without_worker_url(self):
        with patch.object(main, "PADDLEOCR_VL_URL", ""):
            response = await self.client.post(
                "/api/document/parse",
                files={"file": ("sample.png", b"not-read-because-unconfigured", "image/png")},
            )
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
