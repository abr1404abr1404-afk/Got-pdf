"""Password-authenticated PDF unlocking; never bypasses passwords or owner permissions."""
from __future__ import annotations

import io
import pymupdf

MAX_UNLOCK_PAGES = 200


def unlock_pdf_bytes(data: bytes, password: str) -> bytes:
    if not isinstance(password, str) or not password or len(password) > 256:
        raise ValueError("أدخل كلمة مرور صحيحة لا تتجاوز 256 حرفًا.")
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("الملف ليس PDF صالحًا.") from exc
    try:
        if not document.needs_pass:
            return data
        auth = document.authenticate(password)
        if auth <= 0:
            raise ValueError("كلمة المرور غير صحيحة.")
        if document.page_count < 1 or document.page_count > MAX_UNLOCK_PAGES:
            raise ValueError("عدد صفحات الملف يتجاوز الحد المسموح لفك القفل.")
        # A user password may permit viewing but prohibit modification.
        if auth != 2 and not (document.permissions & pymupdf.PDF_PERM_MODIFY):
            raise PermissionError("كلمة المرور صحيحة، لكن مالك الملف لم يسمح بالتعديل. يلزم إذن المالك.")
        output = document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_NONE,
            garbage=4,
            deflate=True,
            clean=True,
        )
        if not output.startswith(b"%PDF-"):
            raise ValueError("تعذّر إنشاء نسخة PDF مفتوحة.")
        return output
    finally:
        document.close()
