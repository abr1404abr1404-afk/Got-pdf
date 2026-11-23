# Alfalqi PDF — Feature Selection & Integration Plan

This document is the engineering decision record for expanding Alfalqi PDF into a unified document workspace. A feature is not considered shipped merely because a dependency or UI control exists: it must be wired end-to-end, tested, documented, and enabled on a supported deployment.

## Current verified baseline (source inspection)

- Browser PDF editor and page/image/text overlay workflows are in `index.html`.
- Backend OCR supports Tesseract and optional PaddleOCR; `OCR_MODE` selects hybrid, PaddleOCR, or Tesseract.
- The committed Render Blueprint uses `Dockerfile.free` and Tesseract only. The full `Dockerfile` installs PaddleOCR and is not the free Render deployment.
- The frontend has a browser Tesseract fallback.
- Backend compression uses PyMuPDF.
- AI chat and extraction are optional and require an owner-configured provider key.
- Drive/QR sharing is a user-consent flow and remains dependent on Google OAuth/Drive configuration.
- Existing table extraction is based on visible ruled lines; it is not a general table-understanding engine.

## Selection principles

1. Prefer open-source components with a license compatible with the distribution model; audit model weights, fonts, and transitive dependencies separately.
2. Keep resource-heavy inference out of the small free web service. Use browser processing or separately deployable workers.
3. Keep user files local by default. Any upload to a third-party service must be explicit and explained.
4. Add adapters behind stable internal interfaces; do not bind the UI to one vendor or engine.
5. Use a representative Arabic/English evaluation set and report CER/WER, table accuracy, latency, memory, and failure rate before selecting defaults.
6. Do not silently replace existing working functionality. Every migration must preserve a fallback and have regression tests.

## Feature-to-engine decisions

| Feature | Selected component / approach | Reason | Status |
|---|---|---|---|
| PDF viewing/rendering | Mozilla PDF.js | Mature browser viewer/rendering stack; suitable foundation for page navigation and text-layer work | Existing frontend viewer must be audited before replacing anything |
| Basic browser-side PDF construction | pdf-lib | Useful for page operations, metadata, forms and drawing; not a general editor for existing page text | Candidate for targeted operations, not a PyMuPDF drop-in |
| Structural PDF operations | QPDF | Strong structural operations, encryption and validation workflows | Candidate backend adapter |
| Lightweight OCR | Tesseract / Tesseract.js | Existing server and browser fallback; suitable for clean printed scans and constrained devices | Existing |
| Advanced OCR and layout | PaddleOCR 3.x | Arabic-capable document OCR/layout family; can run as an optional worker | Existing optional backend code; benchmark and deployment verification required |
| Searchable scanned PDF | OCRmyPDF | Adds a searchable text layer and provides scan cleanup workflows | Planned worker integration |
| Document structure, tables and reading order | Docling, benchmarked against PaddleOCR PP-Structure | Structured extraction and document understanding; use only after Arabic benchmark and model-license review | Planned |
| Office-to-PDF | Gotenberg 9 + LibreOffice | Stable HTTP boundary for Office conversion and PDF processing | API adapter merged; requires separately configured Gotenberg service |
| Camera document capture | Browser camera capture + existing pdf-lib image pipeline | Local multi-page capture without uploading photos to the app server | Added in PR #27; device testing required |
| OCR quality measurement | Project OCR functions + ground-truth manifest + CER/WER | Compare actual deployed engine configurations on identical labeled samples | Benchmark harness added in PR #27; no scores until a labeled dataset is supplied |
| PDF/A and PDF/UA validation | veraPDF plus Gotenberg validation/remediation where appropriate | Standards validation must be explicit and report residual issues | Planned |
| AI assistant | Provider-neutral adapter; local model option later | Avoid hard dependency on one paid API; retain explicit consent | Existing optional external-provider path |
| QR and cloud sharing | Browser-side QR + Google Drive API with explicit OAuth consent | Avoid storing users' files on Alfalqi servers | Existing UI; live integration remains configuration-dependent |

## First implementation in this series: Office conversion

Added optional endpoint:

- `POST /api/convert/office-to-pdf`
- Multipart field: `file`
- Accepted extensions: DOC, DOCX, ODT, RTF, TXT, XLS, XLSX, ODS, PPT, PPTX, ODP.
- Calls only the operator-configured `GOTENBERG_URL`; callers cannot supply an upstream URL.
- Applies upload limits, request limits, a single conversion slot, timeout handling, output-size validation, and PDF signature validation.
- `GET /api/health` reports whether the optional integration is configured.
- Disabled by default. Render Free does not run Gotenberg and must not be described as supporting live Office conversion until a separate service is deployed and tested.

## Next implementation order

### P0 — foundation and compliance
- Resolve project licensing before public distribution. PyMuPDF's AGPL/commercial licensing must be reconciled with the product's distribution and hosting model.
- Add a dependency/model/font license inventory and automated dependency scanning.
- Correct documentation so free deployment, full OCR deployment, and optional integrations are never conflated.
- Add API contract tests and browser smoke tests.

### P1 — Arabic OCR quality
- Populate the new `tools/ocr_benchmark.py` manifest with a private, consented benchmark set and ground-truth text/page layout; run it on a machine with the required OCR engines.
- Compare Tesseract, PaddleOCR, and hybrid output on printed Arabic, mixed Arabic/English, low-resolution scans, skewed photos, tables, and multi-column pages.
- Measure CER, WER, reading-order accuracy, table-cell accuracy, latency and peak memory.
- Add a review/correction UI with confidence and source bounding boxes.
- Integrate OCRmyPDF only as a separate optional worker for searchable-PDF output.

### P2 — structured document intelligence
- Evaluate Docling and PaddleOCR PP-Structure on the same benchmark.
- Export tables to XLSX/CSV with page references and confidence.
- Add document-to-Markdown/JSON export without silently losing layout.

### P3 — professional PDF workspace
- Audit PDF.js viewer capabilities before changing the current renderer.
- Add page thumbnails, search, bookmarks, annotations, form filling and undo/redo as separate tested increments.
- Treat editing existing text as a specialized reconstruction problem, not as a simple overlay.
- Add true redaction with content removal and post-save verification; a white rectangle is not redaction.

### P4 — conversion, standards and security
- Complete Gotenberg deployment and real Office round-trip tests using Arabic fonts.
- Add veraPDF validation reports for PDF/A and PDF/UA; never claim conformance without validation.
- Add digital signatures only with certificate/key handling and signature verification; a drawn signature is not a cryptographic signature.
- Add batch jobs only after queueing, timeouts, quotas and cancellation are implemented.

## Release gates

A feature can be marked **available** only when:
- its dependency and model licenses are recorded;
- backend and frontend paths are connected;
- automated tests pass;
- at least one representative Arabic and one English fixture pass;
- resource limits and failure behavior are tested;
- privacy and external data flow are documented;
- deployment configuration is actually enabled.

A feature that has code but lacks a configured service is labelled **optional / not enabled**. A feature with a UI but no complete implementation is labelled **planned**, not available.
