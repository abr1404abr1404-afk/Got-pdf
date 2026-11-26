# Real Image OCR Test — IMG_4660.jpeg

Date: 2026-11-27

## Input and scope

- User-provided image: `IMG_4660.jpeg`
- Format: JPEG
- Dimensions: 706 × 1536 px
- Content: mobile browser screenshot of the PDF editor; the visible document is an Arabic educational infographic embedded within the screenshot.
- The screenshot includes browser chrome and editor toolbars. OCR on the whole screenshot is therefore expected to include UI text as well as document text.

## Local baseline measurements

The local test used Tesseract with Arabic and English language data, OEM 1, PSM 11, and a mild CLAHE contrast normalization comparable to the server preprocessing. These are local measurements, not a live Render API result.

| Test region / mode | Recognized characters (approx.) | Observation |
|---|---:|---|
| Full screenshot, PSM 11 | 907 | Captures both UI and infographic; some small infographic labels are inaccurate |
| Infographic crop, PSM 6 | 546 | Better focus, but several small labels and words remain distorted |
| Infographic crop, CLAHE + 2× upscale, PSM 6 | 559 | Slightly more text, no reliable correction of all small labels |
| Infographic crop, tiled semantic bands, PSM 11 | 104 + 70 + 122 + 165 (per-band output) | Smaller regions expose additional words and improve segmentation; overlaps and repeated text mean counts must not be summed as unique text |

Character counts are not accuracy scores. No verified ground-truth transcription was supplied, so CER/WER cannot responsibly be reported from this image alone.

## Findings

1. The input is a screenshot, not a clean scan. The UI contributes noise and unrelated text.
2. The infographic's smaller text is the difficult portion; large headings are recognized more consistently.
3. Region-based recognition improves access to small text compared with relying only on a single full-page pass.
4. Aggressive binarization is not a safe universal default for Arabic because dots and thin strokes can disappear.
5. This sample does not test handwriting recognition; the visible content is printed infographic text.

## Code change

The OCR pipeline now has a bounded tiled recovery pass for tall images when the full-page Tesseract result has mean confidence below 82:

- At most three overlapping horizontal tiles.
- Portrait-only activation (height/width >= 1.35).
- Tile resize capped at 2× and 2200 px longest edge.
- Per-tile OCR timeout capped at 8 seconds.
- Word and line bounding boxes are mapped back into the preprocessed source-image coordinate space.
- The pass is skipped after a Tesseract timeout and is not used for landscape images.

This is a targeted recovery path, not a guarantee that every small label is correct. The editor must continue to expose OCR text for user review.

## Verification status

- Local OCR baseline on the exact uploaded image: completed.
- Tiled OCR behavior and coordinate mapping: covered by `tests/test_ocr_tiled.py`.
- Frontend static checks: passed in the associated GitHub Actions run.
- Full Python test suite and real PDF-to-DOCX workflow: pending GitHub Actions at the time this report was written.
- Live Render API test: not completed because the test environment could not resolve `got-pdf.onrender.com`; do not treat local OCR as proof that the deployed API is healthy.
