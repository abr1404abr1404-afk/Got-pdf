# Arabic PDF Text Replacement — Validation Gate

## Current status

Arabic text replacement is intentionally not enabled. The existing editor continues to support only isolated, horizontal Latin text spans when the original font and replacement width can be validated.

## Technical investigation

PyMuPDF's `Page.insert_htmlbox()` uses its Story layout engine and HarfBuzz for complex-script shaping, including right-to-left languages. An isolated rendering experiment in the current development environment displayed Arabic text with connected glyphs and correct RTL visual order when the HTML paragraph explicitly used `dir="rtl"`.

However, extracting the inserted text from the resulting PDF did not preserve the original Unicode sequence reliably: Arabic glyphs were returned as presentation forms and at least one ligature was mapped to an unrelated character. A direct text search for the original Arabic phrase also failed. A visually correct but non-searchable or incorrectly mapped replacement is not acceptable for this product.

## Release criteria

Arabic replacement must remain disabled until automated tests demonstrate all of the following:

1. Correct visual joining and shaping for Arabic letters, including beginning, middle, end, and isolated forms.
2. Correct RTL paragraph order and mixed Arabic/Latin/numeral ordering.
3. Correct Unicode text extraction and PDF text search after saving and reopening the output.
4. Preservation of neighboring text, images, vector objects, annotations, and the source PDF.
5. No clipping: if replacement does not fit the original region at the agreed font size, reject it rather than silently shrink or overflow.
6. A supported Arabic font is embedded in the output and its license is reviewed.
7. Regression coverage for diacritics, punctuation, Arabic-Indic digits, Latin digits, and common ligatures.

## Safe current behavior

The editor must continue to reject Arabic replacement rather than silently use a Latin-only insertion method. Users can still add Arabic as a separate overlay through the existing text annotation workflow, but that is not a replacement of the underlying PDF text.
