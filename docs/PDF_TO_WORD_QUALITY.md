# PDF-to-Word quality diagnostics

The PDF-to-DOCX endpoint returns the converted DOCX and a set of response headers with approximate quality indicators.

## Indicators

- **Text coverage**: percentage of extractable source PDF word tokens that also appear in the DOCX.
- **Text precision**: percentage of DOCX word tokens that also appear in the extractable source PDF.
- **Matched/source/output words**: token counts used for those percentages.
- **Structure counts**: DOCX paragraphs, tables and inline images, plus PDF image occurrences.

Text comparison uses Unicode NFKC normalization, case folding and token matching. This is intended as a warning signal, not a proof of semantic correctness or visual fidelity. Reordered text, ligatures, OCR differences, headers/footers, repeated words, Arabic shaping and complex columns can affect the scores.

## Scanned documents

If the PDF contains no extractable text, the response reports `no_extractable_source_text` and omits coverage/precision. Image counts are diagnostic only: they do not establish that every scanned page was preserved or that OCR was performed.

## Limits and privacy

The analyzer follows the converter's 20-page limit and stops source text analysis above 1.5 million extracted characters. It does not retain a copy of the source or output. The frontend displays the indicators after conversion, and users should inspect the resulting DOCX before relying on it.

## API response headers

- `X-Conversion-Analysis`
- `X-Conversion-Source-Words`, `X-Conversion-Output-Words`, `X-Conversion-Matched-Words`
- `X-Conversion-Text-Coverage`, `X-Conversion-Text-Precision` (only when measurable)
- `X-Conversion-Source-Images`, `X-Conversion-Output-Images`
- `X-Conversion-Output-Tables`, `X-Conversion-Output-Paragraphs`

These headers are exposed through CORS for the GitHub Pages frontend.


## Real Arabic benchmark — 27 November 2026

A repeatable CI test used page 1 of a 16-page public Dubai Government legal PDF. The tested page is 612 × 792 pt. These measurements describe this page only, not general accuracy across all PDFs.

| Route | Text coverage | Text precision | CER against PDF text | LibreOffice page count | Structure |
|---|---:|---:|---:|---:|---|
| Current formatted route (pdf2docx) | 98.65% | 99.32% | 35.89% | 6 | 45 paragraphs, 2 tables |
| Native-text, same-baseline merged candidate | 100.00% | 100.00% | 9.17% | 1 | 28 paragraphs, 0 tables |
| Native word-box grouping candidate | 87.84% | 78.31% | 23.64% | Not selected | 29 paragraphs |
| Scanned-page OCR reconstruction | Not measurable against native text-token coverage | Not measurable | 24.28% | Not yet round-trip measured | 35 paragraphs |

### What improved

- Merging same-baseline native PDF text fragments reduced the experimental output from 72 paragraphs to 28 without losing source word tokens on this page.
- The candidate rendered through LibreOffice to exactly one page, with page width and height matching the source exactly (0.00% size error).
- The OCR-to-Word generator now accepts original page dimensions and applies them to Word sections. A unit test verifies the page size and zero margins.
- CI now checks the candidate's one-page round-trip, exact physical page dimensions, and 100% token coverage.

### Why the candidate is not yet the production default

The source page contains table-like structures. The current converter preserved two Word tables, while the experimental native reconstruction currently produces ordinary paragraphs and no tables. The candidate therefore wins on text order and page count for this fixture but loses a structural feature that matters. It must not silently replace the current route for documents containing tables, images, multiple columns, or complex layouts.

The production route remains unchanged for selectable-text PDFs until a structure-aware hybrid is validated across multiple Arabic and bilingual fixtures. LibreOffice is a repeatable layout diagnostic, not a substitute for Microsoft Word or a visual pixel-level fidelity assessment.


## Experimental simple-page route (opt-in)

A conservative native-text reconstruction path is available behind the backend environment variable `PDF_DOCX_NATIVE_SIMPLE_PAGES=true`. It is **disabled by default**. It is considered only when every page has selectable native text, one detected column, no embedded raster images, and table detection succeeds with no tables. If any page fails a check or table detection is unavailable, the request falls back to the existing `pdf2docx` converter. The route merges same-baseline text fragments while keeping detected columns and regions separate, and preserves source page dimensions.

This gate is intentionally conservative. It is not yet approved as the default production route: the real benchmark still contains table-like structures, and the current evidence is not broad enough to establish general visual fidelity. CI unit tests cover the merge and the table/image/multi-column rejection guards; a broader multi-document benchmark and pixel-level visual comparison are still required before enabling the flag in the hosted service.


## Multi-layout and visual diagnostics

CI now runs `tests/e2e/layout_matrix.py` in addition to the public Arabic legal-PDF benchmark. The matrix creates controlled one-page PDFs for four distinct structures: simple text, ruled table, two columns, and embedded image with caption. Each case is sent through the real formatted-conversion API, the returned DOCX is inspected for editable paragraphs/tables/images, and LibreOffice round-trips it to PDF.

For one-page round-trips, the test rasterizes source and output at the same nominal scale and records normalized mean absolute pixel error plus the percentage of pixels within 24 grayscale levels. If page counts differ, visual comparison is marked not comparable rather than forcing a misleading score. When raster dimensions differ, the output is resized to source dimensions for diagnostic comparison; this is not SSIM and is not proof of layout equivalence. The matrix is synthetic and isolates layout classes; it complements, rather than replaces, the real Arabic source PDF. Its measurements must not be presented as Microsoft Word rendering fidelity.

The native simple-page route remains opt-in and disabled by default. The matrix currently evaluates the public API's production route; the results are used to identify layout regressions before any route-selection policy is widened.
