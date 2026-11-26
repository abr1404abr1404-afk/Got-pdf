# Third-Party Software & Model License Register

> Initial source-level inventory: 2026-11-27. This is an engineering tracking document, **not legal advice or a completed legal clearance**. Verify exact resolved versions, transitive dependencies, bundled binaries, fonts and model weights before release.

## Current direct dependencies

| Component | Declared requirement | Known license / concern | Product decision |
|---|---|---|---|
| FastAPI | `fastapi>=0.115,<1` | MIT | Keep |
| Uvicorn | `uvicorn[standard]>=0.30,<1` | BSD-3-Clause | Keep |
| python-multipart | `python-multipart>=0.0.9` | Apache-2.0 | Keep; track transitive deps |
| Pillow | `pillow>=10.3` | HPND | Keep |
| NumPy | `numpy>=1.26,<2` | BSD-3-Clause | Keep |
| OpenCV headless | `opencv-python-headless>=4.10,<5` | Apache-2.0 for modern OpenCV | Keep |
| pytesseract | `pytesseract>=0.3.13` | Apache-2.0 wrapper; Tesseract executable and traineddata have separate licenses | Keep; inventory binary and language data |
| PyMuPDF | `PyMuPDF>=1.28.0` | AGPL-3.0-or-later or commercial licensing; exact obligations depend on distribution/deployment | **Legal review required before commercial/closed deployment** |
| PaddlePaddle | `paddlepaddle==3.2.0` (full requirements only) | Apache-2.0 project; verify platform wheels and bundled components | Optional heavyweight runtime |
| PaddleOCR | `paddleocr>=3.3,<4` (full requirements only) | Apache-2.0 project; model weights and downloaded assets must be checked independently | Optional worker; no default free-tier loading |
| httpx | `httpx>=0.27,<1` | BSD-3-Clause | Keep |
| python-docx | `python-docx>=1.1,<2` | MIT | Keep |
| openpyxl | `openpyxl>=3.1,<4` | MIT | Keep |
| pdf2docx | `pdf2docx>=0.5.8,<0.6` | MIT project license; upstream maintenance status is limited and it relies on PyMuPDF in this project path | Keep behind converter boundary; don't make it the sole strategy |

## Candidate components (not currently approved as direct dependencies)

| Candidate | Project license | Required separate checks | Status |
|---|---|---|---|
| PDF.js | Apache-2.0 | Bundled fonts/worker assets and exact version | Selective browser use |
| OCRmyPDF | MPL-2.0 | Ghostscript/Tesseract and all system/transitive dependencies; deployment image size | Evaluate in isolated batch worker |
| qpdf | Apache-2.0 | Packaged binary/build provenance | Evaluate for structural PDF cases |
| PDFium | Mixed component licensing, including BSD/Apache-family notices | Full third-party notices and binary provenance | Deferred |
| Surya | Source code and model weights may have different terms | Verify exact model-weight license, restrictions and intended commercial use | Deferred pending review |
| LibreOffice | MPL-2.0 and additional component notices | Distribution package notices, fonts, codecs and headless process isolation | Optional external service |
| HarfBuzz | MIT | Font license and shaping integration | Candidate for Arabic shaping path; not sufficient alone to guarantee PDF Unicode correctness |
| OpenType fonts | Per-font license | Embedding rights, redistribution and subset embedding | Must be reviewed per font |

## Mandatory release process

1. Resolve and freeze the exact production dependency graph for each deployment profile (`requirements.txt`, `requirements-free.txt`, worker images).
2. Generate an SBOM (CycloneDX or SPDX) from the built image/environment, including operating-system packages and binaries.
3. Store license text, source URL, exact version, package checksum, model checksum, and deployment role for every shipped/downloaded component.
4. Treat model weights, OCR language data, fonts and external executables as separate assets; package license alone is not enough.
5. Review PyMuPDF's AGPL/commercial terms against the actual hosted-service and distribution model before launch.
6. Re-run the review whenever a dependency or model version changes.

## Important scope note

This register is intentionally conservative. It records top-level dependencies visible in the repository requirements, not every transitive package or binary currently installed on Render. No claim of complete legal clearance is made until the resolved environment and deployment artifacts have been scanned.
