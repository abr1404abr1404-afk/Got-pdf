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
