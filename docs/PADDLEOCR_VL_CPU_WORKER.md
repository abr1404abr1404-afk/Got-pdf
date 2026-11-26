# PaddleOCR-VL CPU worker (self-hosted)

This worker runs the official PaddleX PaddleOCR-VL serving pipeline on an x86_64 CPU. It is separate from the lightweight Got-pdf API; Got-pdf forwards files to the worker's `/layout-parsing` JSON API.

## Start locally

Requirements: Docker Engine with Compose and enough memory and disk for PaddlePaddle, PaddleOCR dependencies, and downloaded model weights.

```bash
docker compose -f docker-compose.paddle-vl-cpu.yml up --build
```

The service listens on `http://127.0.0.1:8080`. The first startup downloads model weights and may take time. The compose file binds to loopback only; it does not expose an unauthenticated model service to the public internet.

## Connect Got-pdf

Set these server-side environment variables on the Got-pdf API service:

- `PADDLEOCR_VL_URL`: HTTPS base URL of the worker, without `/layout-parsing`.
- `PADDLEOCR_VL_API_KEY`: optional bearer token enforced by your reverse proxy or private gateway.

The worker itself does not enforce the optional bearer token. If the API and worker are on different machines, place the worker behind HTTPS and a gateway that checks the bearer token. Never publish port 8080 directly, and never put the worker URL or token in browser code.

After connecting, `/api/health` reports whether the URL is configured. This is not a live reachability check; submit a real PDF and image to verify the worker.

## API behavior

- `POST /api/document/parse`: returns per-page Markdown and structured layout JSON.
- Multipart `export_docx=true`: Got-pdf requests PaddleOCR-VL's documented native DOCX export when the service returns one complete document. If the service returns page-wise fragments, Got-pdf falls back to an editable DOCX reconstructed from all Markdown pages.
- Complex diagrams, embedded images, equations, and exact page geometry still need visual review.

## Operations and licensing

- PaddleOCR documentation lists x86_64 CPU inference as supported; measure latency on real Arabic files before opening the feature to all users.
- Start with one request at a time on CPU and keep the model cache on persistent storage.
- The worker is independent of Render Free. A remote worker may incur hosting and bandwidth costs.
- The PaddleOCR-VL-1.6 model card declares Apache-2.0. Retain upstream license and notice files; also review licenses for PaddleOCR, PaddleX, PaddlePaddle, and any other dependencies before redistribution.

Official documentation: https://www.paddleocr.ai/v3.6.0/en/version3.x/pipeline_usage/PaddleOCR-VL.html
Model card: https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6
