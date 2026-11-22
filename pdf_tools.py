"""PDF compression helpers: lossless structure cleanup and opt-in image recompression."""
from __future__ import annotations

import fitz


COMPRESSION_LEVELS = {
    "lossless": None,
    "balanced": {"dpi_threshold": 180, "dpi_target": 144, "quality": 82},
    "small": {"dpi_threshold": 140, "dpi_target": 100, "quality": 65},
}


def compress_pdf_bytes(data: bytes, level: str = "balanced") -> tuple[bytes, bool]:
    """Optimize a PDF and return the original if the result is not smaller."""
    if not data:
        raise ValueError("الملف فارغ")
    if level not in COMPRESSION_LEVELS:
        raise ValueError("مستوى الضغط غير صالح")

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("الملف ليس PDF صالحًا") from exc

    try:
        if document.needs_pass:
            raise ValueError("ملف PDF محمي بكلمة مرور")
        if not document.is_pdf:
            raise ValueError("الملف ليس PDF صالحًا")

        image_options = COMPRESSION_LEVELS[level]
        if image_options:
            # Only embedded raster images are recompressed; text and vector content stay intact.
            document.rewrite_images(
                **image_options,
                lossy=True,
                lossless=True,
                bitonal=True,
                color=True,
                gray=True,
                set_to_gray=False,
            )
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
