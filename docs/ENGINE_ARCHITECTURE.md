# Engine Architecture & Adoption Plan

> Status: engineering decision record, 2026-11-27  
> Scope: evolve the existing Alfalqi PDF application without replacing working features or destabilizing the mobile editor.

## 1. Executive decision

Do not introduce a second application framework or a large collection of heavyweight dependencies in one release. The repository already has distinct backend modules for PDF operations, OCR, layout analysis, image cleanup, text styling, searchable PDFs, DOCX export, office conversion, and PaddleOCR-VL integration. The immediate architectural need is **stable engine contracts, measurable routing, and operational isolation**, not a wholesale rewrite.

The current browser-first editor remains the user-facing product. Heavy recognition and conversion engines must be optional capabilities behind the API or a separately provisioned worker. The Render free deployment must not be treated as a suitable host for large OCR models.

## 2. Verified repository baseline

The current default-branch tree contains, among others:

- `main.py`: FastAPI application, OCR orchestration, PDF-to-DOCX adaptive routing, limits and API routes.
- `document_layout.py`, `text_style.py`: layout and text-style analysis.
- `pdf_to_docx.py`, `document_export.py`, `office_conversion.py`: document conversion/export.
- `pdf_image_tools.py`, `image_cleanup.py`: PDF image/object work and image cleanup.
- `searchable_pdf.py`, `pdf_security.py`, `redaction.py`, `pdf_tools.py`, `pdf_compare.py`: PDF operations.
- `paddle_vl_client.py`: remote PaddleOCR-VL client.
- `tests/`: focused unit/API tests; `tests/e2e/` includes editor interaction, real Arabic OCR and PDF-to-DOCX tests.
- `scripts/check_frontend.mjs`: frontend static/regression checks.

The API currently imports PyMuPDF, OpenCV, NumPy, pytesseract and Pillow directly. OCR defaults to Tesseract; Paddle modes require explicit opt-in. PDF-to-DOCX distinguishes native text pages from scanned pages and routes scans through OCR reconstruction. This is a useful baseline to preserve.

## 3. Target architecture

Keep the existing UI and public API stable. Introduce boundaries gradually, one capability at a time.

| Boundary | Responsibility | First implementation | Later candidates |
|---|---|---|---|
| PDF rendering | Render pages consistently; coordinate conversion | Existing browser PDF viewer and current server rendering | PDF.js improvements; evaluate PDFium only if a measured gap remains |
| PDF structure | Inspect text, images, vectors, metadata, permissions | Existing PyMuPDF-backed functions | qpdf for structural operations where it adds a distinct capability |
| OCR recognition | Return normalized words/lines, boxes, confidence, engine metadata | Existing Tesseract path | PaddleOCR as opt-in worker; other engines only after corpus benchmarks |
| Layout | Reading order, RTL/LTR, columns, tables, regions | Existing `document_layout.py` | Dedicated layout models after measured failures |
| Image reconstruction | Remove/replace text while preserving background | Existing OpenCV cleanup preview | Inpainting/reconstruction engine behind preview-and-approve |
| DOCX export | Produce a document with an explicit fidelity mode | Existing pdf2docx and OCR-layout paths | LibreOffice-based office conversion where it solves a demonstrated case |
| Quality gate | Validate text, geometry, visual output, timing and memory | Existing tests and conversion headers | Golden corpus + rendered-page comparison |

### Required normalized OCR result

All OCR engines should eventually map to one internal result shape:

- `engine`, `engine_version`, `language`, `page`
- `image_width`, `image_height`, coordinate-space identifier
- `lines[]`: text, word-level tokens when available, bounding box, confidence, reading order, direction, region, source engine
- `tables[]`: bounding box, rows/cells, confidence and provenance
- `warnings[]`: low confidence, unsupported script, partial result, timeout, fallback
- `timings`: preprocessing, recognition, layout, total

Never silently combine coordinates from different scales. Every box must state whether it is in source-page points, rendered pixels, or normalized page coordinates. Preserve raw engine output for diagnostics, but do not expose it as the stable frontend contract.

## 4. Engine routing policy

1. **Native PDF text first.** Reuse an existing text layer when it is sufficiently populated and geometrically valid. Do not OCR a page merely because OCR is available.
2. **Image quality triage.** Detect rotation, skew, low resolution, contrast and likely multi-column/table layout. Apply only transformations supported by evidence; retain the original image.
3. **Fast baseline.** Run the lightweight configured engine first. Existing Tesseract remains the baseline, not a claim of best accuracy.
4. **Escalate selectively.** Send low-confidence or structurally complex pages to an opt-in worker (for example PaddleOCR) only when that worker is configured and available.
5. **Compare, don't blindly overwrite.** Use confidence, language-aware normalization, geometric consistency and reading-order checks. If engines disagree materially, show a review state rather than inventing certainty.
6. **Return provenance.** Each recognized region must retain its engine and confidence so the user can correct it and understand why.
7. **Bound resources.** Apply page, pixel, byte, time, concurrency and output limits before expensive work. Cancelled/failed operations must not corrupt the original file.

## 5. Arabic text replacement: release blocker

Arabic replacement must remain disabled until it passes all gates in `docs/ARABIC_TEXT_REPLACEMENT.md`. In particular, a visually correct overlay is not enough: after saving and reopening, Unicode extraction, search, copy/paste, RTL order, mixed Arabic/Latin/numerals and diacritics must all be correct. Keep annotation/overlay separate from true replacement in the UI and data model.

Recommended implementation sequence:

1. Detect and classify the original text region and its geometry.
2. Capture original font properties and background/overlap constraints.
3. Shape Arabic with a verified OpenType shaping path and an embeddable, license-cleared font.
4. Fit text without silent clipping or destructive shrinking.
5. Save to a temporary output; reopen and validate extraction/search and object preservation.
6. Render before/after previews; require explicit approval when background reconstruction is uncertain.
7. Promote only if visual and semantic gates pass; otherwise reject safely and preserve the source.

## 6. PDF-to-Word: expose fidelity, not a misleading single promise

Maintain distinct conversion modes:

- **Visual fidelity:** prioritize page appearance; content may be less naturally editable.
- **Editable structure:** prioritize paragraphs, tables and reading order; visual differences are expected.
- **Hybrid:** preserve page geometry and use editable text where reliable, with page imagery for difficult regions.

The current quality headers (coverage/precision and object counts) are useful diagnostics but are not proof of layout fidelity. Add rendered-page comparison, table-cell checks, RTL reading-order checks and explicit mode labels before claiming parity. Keep the current 20-page converter guard until resource tests justify a change.

## 7. Dependency adoption decisions

| Candidate | Decision | Reason / gate |
|---|---|---|
| PDF.js | Adopt selectively in browser | Apache-2.0; useful for rendering/text-layer and viewer work. Avoid duplicate rendering stacks unless there is a measured gap. |
| OpenCV | Keep | Already used for preprocessing and image operations. Add algorithms only with before/after corpus evidence. |
| PaddleOCR | Keep optional | Already present in the full requirements; heavyweight and must stay opt-in/worker-based. Benchmark model weights and deployment memory separately. |
| OCRmyPDF | Evaluate as an optional batch pipeline | Useful for searchable-PDF workflows; adds external/system dependencies and should not be installed into the lightweight web process without a deployment case. |
| qpdf | Evaluate for structural PDF tasks | Apache-2.0; use only where its structural repair/inspection adds value beyond current functions. |
| PDFium | Defer | A second PDF engine adds binary/build complexity. Adopt only for a documented rendering/compatibility gap. |
| Surya | Defer pending model-weight license and benchmark review | Do not infer model-weight permissions from source-code license. Existing benchmark results are not enough to justify deployment. |
| LibreOffice | Keep as an optional isolated conversion service | Useful for office-format conversion; isolate process, enforce time/output limits, and verify deployment availability. |
| pdf2docx | Retain behind an adapter for now | Existing route is functional but should not be the only strategy. It is not actively maintained upstream; validate against fixtures and track PyMuPDF licensing exposure. |

## 8. Licensing and deployment gates

- Maintain `THIRD_PARTY_LICENSES.md` and eventually generate an SBOM from the resolved deployment environment (not just the top-level requirements).
- Review PyMuPDF/MuPDF licensing before distributing or operating the relevant code in a closed-source/SaaS model. PyMuPDF offers AGPL and commercial licensing; obtain a qualified review for the actual deployment model.
- Review model-weight terms separately from Python package licenses.
- Record versions, source URLs, license identifiers, model checksums and whether each component is shipped, downloaded at runtime, or provided by an external service.
- Keep heavyweight OCR out of the constrained free web process. Prefer local browser OCR where it is viable, or a separately provisioned worker with explicit queue/time/memory limits.

## 9. Non-regression requirements

The existing mobile editing and scrolling behavior is a product requirement, not incidental styling. Before changing the editor:

- Capture interaction tests for toolbar placement near all viewport edges, visualViewport/keyboard changes, zoom, touch scroll, drag, selection and dismissal.
- Preserve the old toolbar interaction model unless a tested improvement is demonstrably better.
- Keep editing controls reachable and do not let fixed toolbars block document navigation.
- Run frontend checks and browser E2E tests after every UI change; a static test is not a substitute for iPhone touch validation.

## 10. Quality gates and release metrics

Every engine change must report, by document category:

- CER and WER against verified references, including Arabic diacritics policy.
- Region detection recall/precision separately from character recognition.
- Reading-order accuracy and RTL/LTR mixed-content accuracy.
- Table structure accuracy (rows, columns, cell assignment).
- Visual similarity after PDF/DOCX round-trip, plus clipping/overlap checks.
- Median and p95 latency, peak memory, timeout rate and failure rate.
- Edit persistence, undo/redo and original-file integrity.

Do not publish one overall OCR score that hides handwriting, decorative fonts, tables or low-contrast failures. A category with no reference samples must be marked **not measured**, not successful.

## 11. Execution sequence

### Phase A — baseline and safety
- Freeze representative fixtures and expected outputs.
- Run all current unit/API/frontend/E2E checks and record failures separately from product defects.
- Produce resolved dependency inventory and licensing review.
- Keep current public routes and UI unchanged.

### Phase B — contracts and observability
- Add normalized engine result contracts and adapters around existing functions.
- Add structured timings, provenance and warning codes.
- Add deterministic tests for coordinate transforms and result normalization.

### Phase C — OCR quality
- Expand the authorized golden corpus across print, scans, handwriting, decorative text, tables, columns and mixed scripts.
- Benchmark current engines on identical samples and settings.
- Route only demonstrably difficult pages to optional workers.

### Phase D — reconstruction and DOCX
- Implement replacement as a separate, gated pipeline.
- Add explicit DOCX fidelity modes and visual regression tests.
- Do not remove the existing converter until a replacement wins on the same corpus.

### Phase E — deployment and productization
- Separate CPU-heavy work into a provisioned worker.
- Add queue visibility, cancellation, cleanup and operational telemetry.
- Only then consider additional engines or a frontend module split.

## 12. Definition of done

A capability is not "complete" because its endpoint returns HTTP 200. It is complete only when it passes functional, semantic, visual, resource, security and mobile-regression checks on representative fixtures, and its limitations are visible to the user.
