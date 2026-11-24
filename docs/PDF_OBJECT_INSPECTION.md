# Native PDF object inspection

The API endpoint `POST /api/pdf/objects/inspect` creates a bounded inventory of page objects without rasterizing the document.

## Detected object types

- **Text spans:** extracted text fragments and normalized page coordinates.
- **Raster images:** dimensions, image reference where available, and normalized bounding box.
- **Vector drawings:** bounding box, path item count, fill and stroke colors where available.
- **Annotations:** annotation subtype and bounding box.

Coordinates are normalized to the page rectangle (0–1), so a client can map an object to its page preview at different zoom levels.

## Safety and limits

- The same PDF validation and 200-page maximum as the image tools applies.
- Inventory is capped at 500 objects per request.
- Text previews are capped at 240 characters per span.
- Overlap warnings identify raster images intersecting text spans or other raster images. These are review hints, not proof that editing will damage content.
- The inspection endpoint does not modify the source PDF.
- `POST /api/pdf/objects/edit` currently supports deleting isolated vector drawings only. It creates a new PDF copy; the input bytes remain unchanged.
- A vector deletion is rejected if its bounding box intersects any text span, raster image, or other vector drawing. This conservative check can reject some safe edits, but avoids knowingly deleting overlapping content.
- The raster-image edit endpoint remains separate and limited to embedded raster images. Text spans, fonts, and page backgrounds are not independently editable yet.

## First editable object operation\n\nThe object inspector UI offers a delete action for vector drawings. The server rechecks the object ID and normalized bounding box against the submitted PDF, rejects stale selections, validates all operations before applying any, and returns a new PDF. It does not support vector recoloring, path reshaping, text replacement, or annotation editing yet. Object IDs are request-local; re-run inspection after every edit.\n\n## Known limitations

Some PDFs flatten text, diagrams, and images into one page-sized image. Such content cannot be separated reliably into its original objects. Complex clipping masks, transparency groups, patterns, form XObjects, and unusual PDF structures may also require specialized handling. The inventory is an aid for selection and review, not a complete semantic interpretation of every PDF operator.

## API response

The response includes page count, object count, per-type counts, objects, and warnings. Each object includes a stable-for-this-response ID, page number, type, and normalized rectangle. IDs are not persistent across document edits; clients should re-inspect after every transformation.
