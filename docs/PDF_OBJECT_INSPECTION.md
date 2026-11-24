# Native PDF object inspection

The API endpoint `POST /api/pdf/objects/inspect` creates a bounded inventory of page objects without rasterizing the document.

## Detected object types

- **Text spans:** extracted text fragments, normalized page coordinates, font family, font size, style flags, color, baseline origin, and writing direction where the PDF exposes them.
- **Raster images:** dimensions, image reference where available, and normalized bounding box.
- **Vector drawings:** bounding box, path item count, fill and stroke colors where available.
- **Annotations:** annotation subtype and bounding box.

Coordinates are normalized to the page rectangle (0–1), so a client can map an object to its page preview at different zoom levels.

## Safety and limits

- The same PDF validation and 200-page maximum as the image tools applies.
- Inventory is capped at 500 objects per request.
- Text previews are capped at 240 characters per span.
- Overlap warnings identify raster-image/text, image/image, vector/text, vector/image, and vector/vector intersections. These are conservative review hints, not proof that editing will damage content.
- The inspection endpoint does not modify the source PDF.
- `POST /api/pdf/objects/edit` currently supports deleting isolated vector drawings only. It creates a new PDF copy; the input bytes remain unchanged.
- A vector deletion is rejected if its bounding box intersects any text span, raster image, or other vector drawing. This conservative check can reject some safe edits, but avoids knowingly deleting overlapping content.
- The raster-image edit endpoint remains separate and limited to embedded raster images. Text spans, fonts, and page backgrounds are not independently editable yet.

## First editable object operation\n\nThe object inspector UI offers a delete action for vector drawings. The server rechecks the object ID and normalized bounding box against the submitted PDF, rejects stale selections, validates all operations before applying any, and returns a new PDF. It does not support vector recoloring, path reshaping, text replacement, or annotation editing yet. Object IDs are request-local; re-run inspection after every edit.\n\n## Known limitations

Some PDFs flatten text, diagrams, and images into one page-sized image. Such content cannot be separated reliably into its original objects. Complex clipping masks, transparency groups, patterns, form XObjects, and unusual PDF structures may also require specialized handling. The inventory is an aid for selection and review, not a complete semantic interpretation of every PDF operator.

## API response

The response includes page count, object count, per-type counts, objects, and warnings. Each object includes a stable-for-this-response ID, page number, type, and normalized rectangle. IDs are not persistent across document edits; clients should re-inspect after every transformation.


## Safe isolated text deletion

The object editor also supports deleting one short text span (up to 240 characters) when it is isolated from all other text spans, raster images, vector drawings, and annotations. The client submits the inspection ID, normalized rectangle, and SHA-256 text fingerprint. The server revalidates all three against the uploaded PDF, applies a text-only redaction, then compares the remaining extracted text spans with the expected sequence. If any neighboring text changes, the operation is rejected and no output is returned. This is deletion only; replacement, reflow, and exact font-preserving text editing are not yet supported. Flattened/scanned text is not editable as a text object.


## Limited Latin text replacement

A first replacement milestone supports one isolated, horizontal Latin text span at a time. The server verifies the span ID, SHA-256 fingerprint, normalized bounds, and absence of intersections with other text, images, vector drawings, or annotations. It retains the original baseline, approximate font size, color, and the embedded font when extractable; otherwise only common Base-14 font families are accepted. Replacement text must fit within the original span width. Arabic, bidirectional text, complex scripts, reflow, and exact font/layout preservation are deliberately rejected in this milestone pending dedicated shaping and rendering tests. The original PDF remains unchanged.


## Safe vector recoloring

The inspector exposes path type and line style metadata. Recoloring is currently restricted to an isolated single rectangle or straight line. The server verifies the object ID and page bounds, rejects intersections with text, images, other drawings, or annotations, removes the old path, then recreates the same geometry with the requested stroke and/or fill color while retaining width and opacity. Complex paths, curves, grouped drawings, and overlapping content are rejected. The original file is never overwritten.


## Safe vector scaling

The editor also scales isolated single rectangles and straight lines between 50% and 200% around their center. Both the original and proposed bounds are checked against text, raster images, other vector paths, annotations, and page edges before the old drawing is removed. Only simple one-item rectangle/line paths are supported; complex paths and grouped graphics are rejected.


## Vector stroke styling

Isolated simple rectangles and straight lines can also change stroke width (0.1–20 pt) and stroke opacity (0–1). The same overlap and object-identity checks apply. Filled-only shapes without a stroke and complex/grouped paths are rejected. The original PDF remains unchanged.


## Moving vector objects

Simple isolated rectangles and straight lines can be moved by a bounded offset of −500 to +500 PDF points. The original and proposed bounds are checked against page edges, text, raster images, other vectors, and annotations. Complex paths and overlapping objects are rejected. The editor returns a new PDF copy.


## Raster image movement and safer editing

The embedded-image editor supports deleting, resizing (10%–400%), and moving an isolated image occurrence by up to 500 PDF points in either direction. Before destructive redaction, the service rejects overlap with text spans, other image occurrences, vector drawings, annotations, and page boundaries; proposed placement is checked against the same content types. These are conservative bounding-box checks, not pixel-level semantic understanding. Repeated uses of the same image resource on one page must be edited one occurrence at a time in separate requests. The source PDF is never modified in place.


## Safe raster image rotation

The raster image editor supports 90°, 180°, and 270° rotation for an isolated embedded image occurrence. Quarter-turn rotations swap the placement width and height around the image center; half-turn rotation retains the original placement bounds. The same overlap checks used by move/resize run before redaction and reinsertion. Rotation can be included in the existing multi-image operation batch (up to 200 operations), while duplicate placements of the same image resource on one page must still be submitted separately. Only a new PDF copy is returned.


## Batch image operations

The image manager supports selecting multiple distinct embedded images and applying their requested actions in one request. The UI includes select-all and clear-selection controls. The service validates each operation before returning an output; a failed operation rejects the request, and the caller's original PDF bytes remain unchanged. Identical image resources reused multiple times on one page remain limited to one selected occurrence per request.


## Raster image enhancement

The editor supports grayscale conversion and bounded brightness, contrast, color, and sharpness adjustments on embedded raster images. Processing is capped at 20 million pixels per image; images with separate transparency masks are rejected rather than risk losing transparency. Enhancements preserve the selected image's placement and return a new PDF copy. Visual fidelity depends on the source image's color profile and format.


## Arabic RTL text replacement — temporarily disabled

Automated CI testing found that the current MuPDF HTML shaping path can produce unreliable extracted Unicode/ToUnicode text even when it renders glyphs. Because this can make the resulting PDF visually or semantically incorrect, the API now fails closed and the frontend action is disabled. No output PDF is produced and the source remains unchanged. Re-enable only after tests verify both rendered Arabic appearance and correct searchable/copyable logical text across representative fonts, diacritics, and mixed-script cases.

