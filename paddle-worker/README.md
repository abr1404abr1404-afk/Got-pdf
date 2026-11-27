---
title: Got-pdf PaddleOCR Worker
sdk: docker
app_port: 7860
---

# Got-pdf remote PaddleOCR worker

A separate CPU inference service for Got-pdf. It uses PaddleOCR PP-OCRv5 Arabic, which also recognizes English text. The worker is deliberately separate from the small Render API container.

## Required secret

Set `PADDLE_WORKER_API_KEY` as a secret in the hosting provider. Use a long random value. The OCR endpoint refuses requests until this secret exists and requires it as a Bearer token. Do not place this secret in GitHub Pages, `config.js`, or browser JavaScript.

## Runtime

- Python 3.11
- PaddlePaddle 3.2.2 CPU
- PaddleOCR 3.7.0
- 2 CPU threads by default; one inference at a time
- 12 MB upload and 12-megapixel image limits by default
- Model weights are downloaded at first inference and cached only for the life of the instance unless persistent storage is configured.

## API

- `GET /api/health`: process health and model-loaded state; it does not run inference.
- `POST /api/ocr/image`: multipart fields `file` and `language` (`ara`, `eng`, `ara+eng`), Bearer authentication required.
- Response fields match the Got-pdf OCR image contract: `engine`, `image_width`, `image_height`, `lines`, `tables`.

## Connect to Got-pdf

Set these variables on the **Render API service**, not the browser:
- `PADDLEOCR_REMOTE_URL`: worker HTTPS base URL, without a trailing slash.
- `PADDLEOCR_REMOTE_API_KEY`: same value as `PADDLE_WORKER_API_KEY`.

Keep `OCR_MODE=hybrid`. Got-pdf sends OCR images server-to-server to this worker. The secret never reaches the browser. If the worker is unavailable or returns no useful text, hybrid mode falls back to Tesseract. Explicit `engine=paddleocr` requests do not silently switch engines.

## Hosting notes

This directory can be used as the source of a separate Docker service. Hugging Face Spaces documents CPU Basic at 2 vCPU / 16 GB RAM, but Docker/Gradio compute Spaces require an eligible paid plan even though the CPU hardware itself has no hourly compute charge. Free hardware may sleep when idle. Therefore this is a deployment target to evaluate, **not a guaranteed always-on free server**. Confirm the account's current plan and terms before creating a Space.

A private network or HTTPS gateway with bearer-token validation is recommended. Do not expose the worker without authentication. CPU inference is slower than a GPU; measure Arabic scans, latency, memory, and cold-start before routing production traffic.
