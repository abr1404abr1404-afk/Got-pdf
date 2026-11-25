"""Bounded batch PDF compression and safe ZIP packaging."""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import PurePath
from typing import Iterable

from pdf_tools import compress_pdf_bytes

MAX_BATCH_FILES = 10
MAX_FILENAME_LENGTH = 100


def _safe_pdf_name(filename: str, used: set[str]) -> str:
    name = PurePath(str(filename or "document.pdf").replace("\\", "/")).name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name.rsplit(".", 1)[0]).strip("._-")
    stem = (stem or "document")[:MAX_FILENAME_LENGTH]
    candidate = f"{stem}.pdf"
    suffix = 2
    while candidate.casefold() in used:
        candidate = f"{stem[:MAX_FILENAME_LENGTH - len(str(suffix)) - 1]}-{suffix}.pdf"
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def compress_pdf_batch(
    files: Iterable[tuple[str, bytes]],
    level: str = "balanced",
    *,
    max_files: int = MAX_BATCH_FILES,
    max_file_bytes: int = 25 * 1024 * 1024,
    max_total_bytes: int = 52 * 1024 * 1024,
    max_output_bytes: int = 100 * 1024 * 1024,
) -> tuple[bytes, list[dict]]:
    """Compress a bounded set of PDFs and return a ZIP plus a per-file report."""
    entries = list(files)
    if not entries:
        raise ValueError("اختر ملف PDF واحدًا على الأقل.")
    if len(entries) > max_files:
        raise ValueError(f"الحد الأقصى للمعالجة الجماعية هو {max_files} ملفات.")
    if level not in {"lossless", "balanced", "small"}:
        raise ValueError("مستوى الضغط غير صالح.")

    total = 0
    used: set[str] = set()
    report: list[dict] = []
    archive_buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for index, (filename, data) in enumerate(entries, start=1):
                if not isinstance(data, bytes) or not data:
                    raise ValueError(f"الملف رقم {index} فارغ أو غير صالح.")
                if len(data) > max_file_bytes:
                    raise ValueError(f"حجم الملف رقم {index} يتجاوز الحد المسموح.")
                total += len(data)
                if total > max_total_bytes:
                    raise ValueError("إجمالي أحجام الملفات يتجاوز حد الطلب الجماعي.")
                output, reduced = compress_pdf_bytes(data, level)
                safe_name = _safe_pdf_name(filename, used)
                archive.writestr(safe_name, output)
                report.append({
                    "name": safe_name,
                    "input_bytes": len(data),
                    "output_bytes": len(output),
                    "saved_bytes": max(0, len(data) - len(output)),
                    "reduced": bool(reduced),
                    "level": level,
                })
            archive.writestr(
                "alfalqi-batch-report.json",
                json.dumps({"count": len(report), "files": report}, ensure_ascii=False, indent=2),
            )
        result = archive_buffer.getvalue()
    except zipfile.BadZipFile as exc:
        raise ValueError("تعذّر إنشاء حزمة ZIP للملفات.") from exc
    if len(result) > max_output_bytes:
        raise ValueError("حجم الحزمة الناتجة يتجاوز الحد المسموح.")
    return result, report
