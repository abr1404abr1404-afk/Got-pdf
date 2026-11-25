"""ASGI smoke tests for the public FastAPI contract.

These tests intentionally avoid OCR model downloads and external services. They
verify that the app imports, the health endpoint responds, and every documented
API route is registered. Feature-specific behavior remains covered by the
focused unit tests in this directory.
"""
import unittest

import httpx

import main


EXPECTED_ROUTES = {
    ("GET", "/api/health"),
    ("POST", "/api/convert/office-to-pdf"),
    ("POST", "/api/pdf/searchable"),
    ("POST", "/api/pdf/unlock"),
    ("POST", "/api/convert/pdf-to-docx"),
    ("POST", "/api/pdf/objects/inspect"),
    ("POST", "/api/pdf/objects/edit"),
    ("POST", "/api/pdf/images/list"),
    ("POST", "/api/pdf/images/edit"),
    ("POST", "/api/pdf/redact"),
    ("POST", "/api/compress/pdf"),
    ("POST", "/api/export/docx"),
    ("POST", "/api/export/xlsx"),
    ("POST", "/api/assistant/chat"),
    ("POST", "/api/assistant/extract"),
    ("POST", "/api/ocr/image"),
    ("POST", "/api/ocr/pdf"),
    ("POST", "/api/pdf/compare"),
}


class ApiSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = httpx.ASGITransport(app=main.app)
        self.client = httpx.AsyncClient(
            transport=self.transport, base_url="http://testserver"
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_health_endpoint_returns_service_capabilities(self):
        response = await self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIs(payload.get("ok"), True)
        self.assertEqual(payload.get("service"), main.APP_NAME)
        self.assertIn("mode", payload)
        self.assertIn("arabic_ocr_ready", payload)
        self.assertIn("searchable_pdf_available", payload)

    async def test_all_expected_api_routes_are_registered(self):
        schema_response = await self.client.get("/openapi.json")
        self.assertEqual(schema_response.status_code, 200)
        schema = schema_response.json()
        actual = {
            (method.upper(), path)
            for path, operations in schema.get("paths", {}).items()
            for method in operations
            if method.lower() in {"get", "post", "put", "patch", "delete"}
        }
        self.assertTrue(
            EXPECTED_ROUTES.issubset(actual),
            f"Missing API routes: {sorted(EXPECTED_ROUTES - actual)}",
        )

    async def test_unknown_api_route_returns_not_found(self):
        response = await self.client.get("/api/__smoke_test_unknown_route__")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
