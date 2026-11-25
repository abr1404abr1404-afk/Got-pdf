"""End-to-end ASGI tests for deterministic document API features.

These tests generate small in-memory documents, call the real FastAPI routes,
and validate returned files. They do not call paid providers or production
services and never persist uploaded data.
"""
import io
import json
import unittest

import httpx
import pymupdf
from PIL import Image

import main


def make_ocr_image(text="INVOICE 12345"):
    image = Image.new("RGB", (1100, 300), "white")
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 78)
    except OSError:
        font = ImageFont.load_default()
    draw.text((55, 85), text, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_pdf(text="Alfalqi PDF API test"):
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((40, 80), text, fontsize=16)
    page.insert_text((40, 150), "Public sample text", fontsize=11)
    image = Image.new("RGB", (24, 18), (210, 45, 35))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(pymupdf.Rect(190, 35, 250, 80), stream=buffer.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


def assert_pdf(testcase, payload):
    testcase.assertTrue(payload.startswith(b"%PDF-"))
    with pymupdf.open(stream=payload, filetype="pdf") as doc:
        testcase.assertGreaterEqual(doc.page_count, 1)


class ApiDocumentFeatureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://testserver",
        )
        self.pdf = make_pdf()

    async def asyncTearDown(self):
        await self.client.aclose()

    def upload(self, name="sample.pdf", payload=None):
        return {"file": (name, payload or self.pdf, "application/pdf")}

    async def test_image_ocr_route_extracts_printed_english_text(self):
        response = await self.client.post(
            "/api/ocr/image",
            files={"file": ("invoice.png", make_ocr_image(), "image/png")},
            data={"language": "eng"},
        )
        self.assertEqual(response.status_code, 200, response.text[:500])
        payload = response.json()
        self.assertTrue(payload.get("lines"))
        recognized = " ".join(line.get("text", "") for line in payload["lines"]).upper()
        self.assertIn("INVOICE", recognized)
        self.assertIn("visual_style", payload["lines"][0])
        self.assertIsInstance(payload["lines"][0]["visual_style"], dict)
        self.assertEqual(payload["lines"][0]["visual_style"]["analysis"], "visual_heuristic")

    async def test_text_cleanup_preview_returns_image_without_applying_changes(self):
        response = await self.client.post(
            "/api/image/text-cleanup/preview",
            files={"file": ("invoice.png", make_ocr_image(), "image/png")},
            data={"bbox": json.dumps([35, 65, 600, 210]), "method": "telea"},
        )
        self.assertEqual(response.status_code, 200, response.text[:500])
        payload = response.json()
        self.assertTrue(payload["preview_image"].startswith("data:image/png;base64,"))
        self.assertFalse(payload["applied"])
        self.assertEqual(payload["details"]["scope"], "selected_region_only")
        self.assertTrue(payload["details"]["preview_only"])
        self.assertGreater(payload["details"]["mask_pixels"], 0)

    async def test_text_cleanup_preview_rejects_invalid_bbox(self):
        response = await self.client.post(
            "/api/image/text-cleanup/preview",
            files={"file": ("invoice.png", make_ocr_image(), "image/png")},
            data={"bbox": json.dumps([2000, 2000, 2200, 2200])},
        )
        self.assertEqual(response.status_code, 400)

    async def test_pdf_ocr_route_processes_a_scanned_page(self):
        scanned = pymupdf.open()
        page = scanned.new_page(width=550, height=150)
        page.insert_image(page.rect, stream=make_ocr_image())
        scanned_bytes = scanned.tobytes()
        scanned.close()
        response = await self.client.post(
            "/api/ocr/pdf",
            files=self.upload(payload=scanned_bytes),
            data={"language": "eng", "dpi": "180"},
        )
        self.assertEqual(response.status_code, 200, response.text[:500])
        payload = response.json()
        self.assertEqual(payload.get("page_count"), 1)
        self.assertTrue(payload.get("pages"))
        self.assertTrue(payload["pages"][0]["ocr"].get("lines"))

    async def test_searchable_pdf_route_returns_searchable_pdf(self):
        ocr_data = {
            "pages": [{
                "page": 1,
                "lines": [{
                    "text": "API searchable layer",
                    "bbox": [50, 95, 240, 115],
                }],
            }]
        }
        response = await self.client.post(
            "/api/pdf/searchable",
            files=self.upload(),
            data={"ocr_data": json.dumps(ocr_data)},
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertEqual(response.headers.get("x-ocr-text-layer"), "invisible")
        assert_pdf(self, response.content)
        with pymupdf.open(stream=response.content, filetype="pdf") as doc:
            self.assertIn("API searchable layer", doc[0].get_text())

    async def test_pdf_object_inspection_route_returns_structured_report(self):
        response = await self.client.post("/api/pdf/objects/inspect", files=self.upload())
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertIn(response.headers.get("content-type", "").split(";")[0],
                      {"application/json"})
        self.assertIsInstance(response.json(), dict)

    async def test_pdf_image_listing_route_finds_embedded_image(self):
        response = await self.client.post("/api/pdf/images/list", files=self.upload())
        self.assertEqual(response.status_code, 200, response.text[:300])
        payload = response.json()
        self.assertGreaterEqual(payload.get("count", 0), 1)
        self.assertGreaterEqual(len(payload.get("images", [])), 1)

    async def test_redaction_route_removes_text_from_returned_pdf(self):
        response = await self.client.post(
            "/api/pdf/redact",
            files=self.upload(payload=make_pdf("PRIVATE-CODE-7341")),
            data={"regions": json.dumps({
                "regions": [{"page": 1, "rect": [0.08, 0.25, 0.72, 0.48]}]
            })},
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertEqual(response.headers.get("x-pdf-redaction"), "permanent")
        assert_pdf(self, response.content)
        with pymupdf.open(stream=response.content, filetype="pdf") as doc:
            self.assertNotIn("PRIVATE-CODE-7341", doc[0].get_text())
            self.assertIn("Public sample text", doc[0].get_text())

    async def test_compression_route_preserves_selectable_text(self):
        response = await self.client.post(
            "/api/compress/pdf", files=self.upload(), data={"level": "lossless"}
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        assert_pdf(self, response.content)
        with pymupdf.open(stream=response.content, filetype="pdf") as doc:
            text = doc[0].get_text()
            self.assertIn("Alfalqi PDF API test", text)
            self.assertIn("Public sample text", text)

    async def test_pdf_comparison_route_reports_changed_content(self):
        revised = make_pdf("Alfalqi PDF API revised")
        response = await self.client.post(
            "/api/pdf/compare",
            files={
                "original": ("original.pdf", self.pdf, "application/pdf"),
                "revised": ("revised.pdf", revised, "application/pdf"),
            },
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        payload = response.json()
        self.assertIn("changed_pages", payload)
        self.assertGreaterEqual(payload["changed_pages"], 1)

    async def test_docx_export_route_returns_valid_office_package(self):
        response = await self.client.post(
            "/api/export/docx",
            json={"pages": [{"page": 1, "text": "Arabic document export test"}]},
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertTrue(response.content.startswith(b"PK"))
        self.assertIn("word/document.xml", __import__("zipfile").ZipFile(
            io.BytesIO(response.content)
        ).namelist())

    async def test_xlsx_export_route_returns_valid_office_package(self):
        response = await self.client.post(
            "/api/export/xlsx",
            json={"pages": [{"page": 1, "text": "Spreadsheet export test"}]},
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertTrue(response.content.startswith(b"PK"))
        self.assertIn("xl/workbook.xml", __import__("zipfile").ZipFile(
            io.BytesIO(response.content)
        ).namelist())

    async def test_pdf_to_docx_route_returns_docx_and_quality_headers(self):
        response = await self.client.post(
            "/api/convert/pdf-to-docx", files=self.upload()
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertTrue(response.content.startswith(b"PK"))
        self.assertEqual(response.headers.get("x-conversion-engine"), "pdf2docx")
        self.assertIn("x-conversion-analysis", response.headers)


if __name__ == "__main__":
    unittest.main()
