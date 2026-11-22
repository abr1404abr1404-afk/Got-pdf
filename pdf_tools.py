"""Lossless PDF optimization helpers used by the optional compression API."""
from __future__ import annotations

import fitz


def compress_pdf_bytes(data: bytes) -> tuple[bytes, bool]:
    """Return a losslessly optimized PDF, or the original if optimization grows it."""
    if not data:
        raise ValueError("الملف فارغ")

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("الملف ليس PDF صالحًا") from exc

    try:
        if document.needs_pass:
            raise ValueError("ملف PDF محمي بكلمة مرور")
        if not document.is_pdf:
            raise ValueError("الملف ليس PDF صالحًا")

        optimized = document.tobytes(
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            use_objstms=1,
        )
    finally:
        document.close()

    if len(optimized) >= len(data):
        return data, False
    return optimized, True
