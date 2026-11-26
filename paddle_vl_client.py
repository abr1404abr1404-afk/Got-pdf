"""Client for a self-hosted PaddleOCR-VL document parsing service.

The heavy model runs in a separately managed open-source worker; the lightweight
PDF API only forwards the uploaded document to the configured private service.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any

import httpx


class PaddleVLError(ValueError):
    """A bounded, user-safe PaddleOCR-VL service error."""


def normalize_paddle_vl_response(payload: dict[str, Any], export_docx: bool = False) -> tuple[dict, bytes | None]:
    if not isinstance(payload, dict):
        raise PaddleVLError("استجابة محرك تحليل المستندات غير صالحة.")
    if payload.get("errorCode", 0) not in (0, None):
        message = str(payload.get("errorMsg") or "تعذّر تحليل المستند.")[:300]
        raise PaddleVLError(message)
    result = payload.get("result")
    if not isinstance(result, dict):
        raise PaddleVLError("لم يُرجع محرك التحليل نتيجة للمستند.")
    raw_pages = result.get("layoutParsingResults")
    if not isinstance(raw_pages, list) or not raw_pages:
        raise PaddleVLError("لم يتمكن محرك التحليل من استخراج صفحات المستند.")
    pages = []
    docx_bytes = None
    markdown_parts = []
    for index, page in enumerate(raw_pages):
        if not isinstance(page, dict):
            continue
        markdown = page.get("markdown") or {}
        markdown_text = markdown.get("text", "") if isinstance(markdown, dict) else ""
        if markdown_text:
            markdown_parts.append(str(markdown_text))
        pages.append({
            "page": index + 1,
            "layout": page.get("prunedResult") if isinstance(page.get("prunedResult"), dict) else {},
            "markdown": str(markdown_text),
        })
        if export_docx and docx_bytes is None:
            exports = page.get("exports") or {}
            docx_export = exports.get("docx") if isinstance(exports, dict) else None
            encoded = docx_export.get("content") if isinstance(docx_export, dict) else None
            if encoded:
                try:
                    docx_bytes = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise PaddleVLError("ملف Word الذي أعاده محرك التحليل غير صالح.") from exc
    normalized = {
        "engine": "PaddleOCR-VL-1.6",
        "page_count": len(pages),
        "pages": pages,
        "markdown": "\n\n".join(markdown_parts),
        "log_id": str(payload.get("logId") or "")[:128],
    }
    if export_docx and (not docx_bytes or not docx_bytes.startswith(b"PK")):
        raise PaddleVLError("لم يُرجع محرك التحليل ملف Word صالحًا.")
    return normalized, docx_bytes


async def parse_with_paddle_vl(
    data: bytes,
    base_url: str,
    file_type: int,
    api_key: str = "",
    export_docx: bool = False,
    timeout_seconds: int = 300,
) -> tuple[dict, bytes | None]:
    if not data:
        raise PaddleVLError("الملف فارغ.")
    if file_type not in (0, 1):
        raise PaddleVLError("نوع الملف غير مدعوم.")
    payload = {
        "file": base64.b64encode(data).decode("ascii"),
        "fileType": file_type,
        "returnMarkdownImages": False,
        "visualize": False,
        "restructurePages": True,
        "mergeTables": True,
        "relevelTitles": True,
        "concatenatePages": True,
    }
    if export_docx:
        payload["outputFormats"] = ["docx"]
    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    timeout = httpx.Timeout(timeout_seconds, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(base_url.rstrip("/") + "/layout-parsing", json=payload, headers=headers)
        response.raise_for_status()
        try:
            response_payload = response.json()
        except ValueError as exc:
            raise PaddleVLError("أعاد محرك التحليل استجابة غير مفهومة.") from exc
    return normalize_paddle_vl_response(response_payload, export_docx=export_docx)
