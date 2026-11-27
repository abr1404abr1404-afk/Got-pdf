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

A repeatable CI test used page 1 of a 16-page public Dubai Government legal PDF. The test converted only the first page, then compared the DOCX text against the PDF's selectable text. These figures describe this one page only; they are not a general accuracy claim.

| Route | Text coverage | Text precision | CER against PDF text | Output structure |
|---|---:|---:|---:|---|
| Current formatted route (pdf2docx) | 98.65% | 99.32% | 35.89% | 27 paragraphs, 2 tables, 0 images |
| Experimental native-text layout candidate | 100.00% | 100.00% | 9.17% | 72 paragraphs, 0 tables, 0 images |
| Scanned-page OCR reconstruction | Not measurable against native text-token coverage | Not measurable | 24.28% | 35 paragraphs, 0 tables, 0 images |

The experimental native-text candidate is **not the production default**. Although its token coverage and CER were better on this page, its generated Word layout split mixed Arabic/number lines and needed two pages in a LibreOffice round-trip. The current pdf2docx result also rendered poorly in that same LibreOffice check, producing six pages from the one-page source. LibreOffice rendering is a useful diagnostic, not a substitute for Microsoft Word testing.

### Decision

- Do not claim layout fidelity based on text coverage or precision alone.
- Keep the existing production converter unchanged while the native-text candidate is improved.
- Next benchmark iteration: merge same-baseline text spans, restore RTL ordering for mixed Arabic/numeric runs, preserve the source page dimensions, and measure page count, table structure, and visual similarity after DOCX rendering.
- A candidate may replace the production path only after it improves text accuracy **and** passes layout checks on multiple Arabic/English fixtures.
