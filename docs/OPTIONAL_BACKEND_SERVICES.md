# Optional backend services — activation and deployment guide

The current Render service is deliberately a lightweight **free-tier** API. It ships Tesseract Arabic/English and the PDF processing stack. The optional integrations below are not activated by changing a frontend flag: each requires a real runtime, provider credential, or separately deployed service.

## Current lightweight backend

- Tesseract Arabic + English: included in `Dockerfile.free`; this is the production OCR fallback.
- PDF parsing/conversion, searchable text layer, redaction, unlock-with-valid-password, image operations: local Python libraries.
- PaddleOCR: not installed in `requirements-free.txt`; not available in the free container.
- PaddleOCR-VL: a separate inference service is required.
- AI assistant: requires a compatible OpenAI API key and a model available to that key.
- Office-to-PDF: requires a reachable Gotenberg 9 service with LibreOffice.

## 1. PaddleOCR / hybrid OCR

The application already supports these environment variables:

| Variable | Value |
|---|---|
| `ENABLE_PADDLE_OCR` | `true` |
| `OCR_MODE` | `hybrid` (recommended) or `paddleocr` |

**Do not add these two variables to the existing free Render instance yet.** The free image does not install PaddlePaddle/PaddleOCR, and adding the full CPU model stack can exceed its memory and startup budget. The full `Dockerfile` installs the packages, but it is not the image selected by `render.yaml`.

Safe activation sequence:
1. Provision a separate service with enough RAM/CPU for PaddlePaddle and model initialization.
2. Build from the full `Dockerfile` (not `Dockerfile.free`).
3. Add `ENABLE_PADDLE_OCR=true` and `OCR_MODE=hybrid` to that service.
4. Run Arabic and English image/PDF regression fixtures and compare CER/WER against a checked ground-truth transcript.
5. Only route production OCR traffic to it after load, memory, cold-start, and accuracy tests pass.

Tesseract remains the fallback in hybrid mode if PaddleOCR fails or returns no usable text.

## 1.1 Remote PaddleOCR worker (recommended for a larger model host)

A separate authenticated worker is now included in `paddle-worker/`. It runs PaddleOCR PP-OCRv5 Arabic on CPU and exposes the same image OCR response contract used by Got-pdf.

1. Deploy the contents of `paddle-worker/` as a separate Docker service with enough RAM and CPU. The first inference downloads model weights and may have a cold-start delay.
2. Set a long random `PADDLE_WORKER_API_KEY` as a secret on the worker.
3. On the Render API service, set `PADDLEOCR_REMOTE_URL` to the worker's HTTPS base URL and `PADDLEOCR_REMOTE_API_KEY` to the same secret.
4. Set `OCR_MODE=hybrid` on the Render API. Do not set the secret in GitHub Pages or `config.js`.
5. Check `/api/health` for `paddleocr_remote_configured=true` and `paddleocr_remote_status=configured_unverified`, then run image and scanned-PDF OCR tests. The status deliberately remains unverified until real worker inference is confirmed.

The API sends images from Render to the worker server-to-server. If the worker fails or produces no useful text, hybrid mode falls back to Tesseract. Explicit Paddle-only requests do not silently switch engines. The worker requires bearer authentication; do not expose it without HTTPS and a secret.

Hugging Face's published documentation lists 2 vCPU and 16 GB RAM for CPU Basic, but Docker/Gradio compute Spaces require an eligible paid plan and free instances can sleep when idle. This is therefore not a guaranteed free always-on deployment. The worker is packaged for deployment there or on another Docker host, but Got-pdf cannot create the external service or set its hosting secrets without account access and explicit setup by the account owner.

## 2. AI assistant

Set these in the backend service's private environment settings:

- `OPENAI_API_KEY`: secret API key; never commit it to Git.
- `OPENAI_MODEL`: model name enabled for that key (default in code: `gpt-4.1-mini`).
- `OPENAI_BASE_URL`: optional compatible API base URL (default: `https://api.openai.com/v1`).

The key is billable provider access. Start with a low usage budget and monitor provider usage. Do not expose it in the frontend or browser JavaScript. Health currently reports whether a key is present; this is configuration status, not proof that the provider accepts the key or that a request succeeds.

## 3. Office / OpenDocument to PDF

Deploy a private Gotenberg 9 service with LibreOffice, then set:

- `GOTENBERG_URL`: the private/internal base URL of that service, without the trailing slash.

The API posts files to `/forms/libreoffice/convert`, limits upload/output sizes, validates the PDF response, and applies a conversion timeout. Do not use an untrusted public demo endpoint for user documents. Validate DOCX, XLSX, PPTX, ODT, and RTL Arabic output on real fixtures before exposing this capability.

## 4. Advanced document parsing (PaddleOCR-VL 1.6)

Deploy the supported PaddleOCR-VL 1.6 inference worker separately, then set:

- `PADDLEOCR_VL_URL`: worker base URL; the API appends `/layout-parsing`.
- `PADDLEOCR_VL_API_KEY`: optional bearer token if the worker is configured to require one.

This worker is substantially heavier than the lightweight API. Use a private service-to-service network where possible. Do not mark the capability ready until a real Arabic PDF and a scan containing tables, images, and multi-column content have passed the parse and DOCX export tests.

## Readiness truth

- `configured` means the required URL/key exists in environment variables.
- `available` in the current health registry mostly reflects configuration or local package presence.
- Neither field guarantees external reachability, valid credentials, model download success, sufficient memory, or acceptable accuracy.
- Keep optional features unavailable in the UI until a real integration smoke test has passed.

## Live functional verification

The workflow `.github/workflows/backend-live-ocr-smoke.yml` uploads only a synthetic image and a synthetic scanned PDF to the live API. It checks known English and Arabic text, not just the health endpoint. It does not send user documents.
