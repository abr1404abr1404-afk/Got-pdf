# PaddleOCR-VL integration

Got-pdf now includes an **optional client** for a self-hosted PaddleOCR-VL 1.6 document-parsing service. The large vision-language model is deliberately kept out of the lightweight Render API container; the existing Tesseract/PyMuPDF routes remain the fallback when the advanced service is not configured.

## Why this engine

- PaddleOCR-VL 1.6 parses document layout, text, tables, formulas, charts, and other document blocks, and supports Arabic among its multilingual languages.
- The code and the published 1.6 model card declare Apache-2.0. Keep the upstream LICENSE/NOTICE notices when redistributing the worker or model.
- The upstream deployment guide recommends a dedicated inference service for production. Its GPU Docker Compose deployment requires a compatible NVIDIA GPU and CUDA 12.6+; CPU inference is also documented, but should be benchmarked before production use.

## Connect a self-hosted worker

Configure these environment variables on the Got-pdf API service:

- `PADDLEOCR_VL_URL`: base URL of the self-hosted PaddleOCR-VL API, without `/layout-parsing`.
- `PADDLEOCR_VL_API_KEY`: optional bearer token if the worker is protected by an authentication proxy.

The worker must expose the upstream `POST /layout-parsing` API. The Got-pdf endpoint forwards the uploaded PDF/image as Base64 using the documented PaddleOCR-VL `/layout-parsing` JSON contract and requests structured Markdown/layout output. When Word export is selected, it requests the documented native `outputFormats: ["docx"]` export. A valid native DOCX is used for a single-page response; for multi-page responses, Got-pdf reconstructs one editable document from all page Markdown rather than accidentally returning only the first page's export.

## API

- `POST /api/document/parse` with multipart `file`: returns per-page layout JSON and Markdown.
- Add multipart `export_docx=true`: returns a native DOCX when a single-page native export is returned, or a multi-page DOCX reconstructed from all Markdown pages.

The API checks PDF passwords, page limits, upload size, image dimensions, response format, and DOCX ZIP signature. If the worker is not configured, the endpoint returns 503 and does not silently claim that PaddleOCR-VL is active.

## Acceptance tests before enabling it

Run the same Arabic test corpus against the existing Tesseract route and PaddleOCR-VL, including:
- printed Arabic books and mixed Arabic/English pages;
- low-quality scans and skewed photographs;
- tables, multi-column pages, headers/footers, and footnotes;
- handwritten pages as a separate category (do not assume printed-text results generalize to handwriting).

Record character error rate (CER), word error rate (WER), reading-order errors, table structure accuracy, DOCX text coverage, visual layout fidelity, latency, peak memory, and failure rate. Do not replace the default OCR engine until the paired benchmark demonstrates a repeatable improvement on Arabic documents.
