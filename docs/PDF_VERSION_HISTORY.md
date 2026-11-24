# Local PDF version history

The optional PDF version history uses browser IndexedDB under `alfalqi-pdf-versions`. It is stored on the current browser and device only; it is not synchronized to an account or uploaded to the server.

## Consent and controls

- Automatic capture is off until the user accepts an explicit consent prompt. The consent explains that opened source PDFs and generated PDF outputs may be stored locally.
- The user can turn automatic capture off or on from the version-history dialog.
- A manual snapshot can be created from the current workspace even when automatic capture is off.
- Users can inspect the list, download a backup copy, delete individual entries, save a snapshot of the current workspace, and restore a selected version.
- Before restoring a version, the current workspace is rendered to a PDF and added to the history so the pre-restore state remains recoverable.
- Each item records its filename, timestamp, byte size, and PDF bytes.

## Compare saved versions

- Select exactly two saved entries in the history list and choose **Compare the two selected versions**.
- Comparison runs locally in the browser; the saved PDFs are not uploaded.
- The tool reports page additions/removals, pages with text changes, up to six added/removed text lines per changed page, and an approximate visual-difference percentage with a changed-area bounding rectangle.
- It compares at most 30 pages per version and caps each rendered page at 1.5 million pixels. Pages are processed sequentially.
- Visual percentages are approximate and can be affected by font substitution, PDF renderer differences, antialiasing, transparency, and page geometry. A high percentage does not identify the semantic reason for a change.

## Retention and failure behavior

- Keeps up to the 5 newest versions.
- Enforces a 100 MiB total retained-data limit; a single PDF larger than the limit is skipped.
- If IndexedDB is unavailable or full, the PDF download/open action continues; the history operation fails without blocking the primary action.
- Restore validates that the selected bytes can be parsed as a PDF before replacing the in-memory workspace.

## Limitations and privacy

- Browser storage can be cleared by the user or evicted by the operating system/browser. Export important files and projects separately.
- Versions are not shared across browsers or devices.
- The history is a bounded snapshot list, not a full keystroke-level undo log or cloud backup.
- Restoring replaces the current in-memory workspace after confirmation; it does not overwrite the saved history item or the original file.
- Automatic capture is consent-based; manually saving a snapshot is an explicit user action.
