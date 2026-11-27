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
