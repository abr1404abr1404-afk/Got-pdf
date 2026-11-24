# Local PDF version history

The app stores generated PDF outputs in browser IndexedDB under `alfalqi-pdf-versions`. This is device- and browser-local storage; it is not synchronized to an account or uploaded to the server.

## Retention and controls

- Keeps up to the 5 newest versions.
- Enforces a 100 MiB total retained-data limit; a single output larger than that limit is not added.
- Each item records its filename, timestamp, byte size, and PDF bytes.
- Users can inspect the list, delete individual entries, save a snapshot of the current workspace, and restore a selected version.
- Before restoring a version, the current workspace is rendered to a PDF and added to the history so the pre-restore state remains recoverable.
- Generated PDFs are added before the browser download/share handoff. If IndexedDB is unavailable or full, the download itself continues and a warning is written to the browser console.

## Limitations

- Browser storage can be cleared by the user or evicted by the operating system/browser. Export important files and projects separately.
- Versions are not shared across browsers or devices.
- The version history stores exported PDF outputs, not every individual keystroke or intermediate editing operation.
- Restoring replaces the current in-memory workspace after confirmation; it does not overwrite the saved history item or original input file.
- This is not a substitute for an external backup.
