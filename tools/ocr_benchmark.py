#!/usr/bin/env python3
"""Evaluate Arabic/English OCR engines against a small, consented ground-truth set.

Run inside the project's backend environment:
  python tools/ocr_benchmark.py --manifest benchmarks/manifest.example.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Iterable


_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Normalize Unicode and Arabic marks without folding distinct letters."""
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\u0640", "")
    value = _ARABIC_DIACRITICS.sub("", value)
    return _WHITESPACE.sub(" ", value).strip().casefold()


def edit_distance(reference: Iterable, hypothesis: Iterable) -> int:
    """Levenshtein distance using O(min(n,m)) memory."""
    a, b = list(reference), list(hypothesis)
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (left != right),
            ))
        previous = current
    return previous[-1]


def error_rate(reference: str, hypothesis: str, unit: str = "characters") -> float:
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)
    if unit == "words":
        ref_units, hyp_units = ref.split(), hyp.split()
    elif unit == "characters":
        ref_units, hyp_units = list(ref), list(hyp)
    else:
        raise ValueError("unit must be 'characters' or 'words'")
    if not ref_units:
        return 0.0 if not hyp_units else 1.0
    return edit_distance(ref_units, hyp_units) / len(ref_units)


def _extract_text(lines) -> str:
    return "\n".join(
        str(item.get("text", "")).strip()
        for item in lines or []
        if str(item.get("text", "")).strip()
    )


def run_benchmark(manifest_path: Path, output_path: Path, engines: list[str]) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples = manifest.get("samples", [])
    if not isinstance(samples, list) or not samples:
        raise ValueError("manifest.samples must contain at least one labeled sample")

    # Import the production pipeline so the benchmark measures the same preprocessing
    # and recognition functions used by the application.
    try:
        import main as ocr
    except Exception as exc:
        raise RuntimeError(
            "Could not import backend OCR dependencies. Run this tool in the backend environment."
        ) from exc

    results = []
    for sample in samples:
        sample_id = str(sample.get("id") or sample.get("image") or "sample")
        image_path = (manifest_path.parent / sample["image"]).resolve()
        reference = str(sample.get("reference", ""))
        language = str(sample.get("language") or manifest.get("language") or "ara")
        if not image_path.is_file():
            raise FileNotFoundError(f"{sample_id}: image not found: {image_path}")

        raw = image_path.read_bytes()
        image = ocr._decode_image(raw)
        prepared = ocr._preprocess(image)

        for engine_name in engines:
            started = time.perf_counter()
            error = None
            try:
                if engine_name == "tesseract":
                    lines, error = ocr._tesseract(prepared, language, 11)
                elif engine_name == "paddleocr":
                    lines, error = ocr._paddle(prepared, language)
                elif engine_name == "hybrid":
                    response = ocr._hybrid(image, language)
                    lines = response.get("lines", [])
                    engine_errors = response.get("engines", {})
                    errors = [v.get("error") for v in engine_errors.values()
                              if isinstance(v, dict) and v.get("error")]
                    error = "; ".join(errors) or None
                else:
                    raise ValueError(f"Unsupported engine: {engine_name}")
                lines = ocr._reading_order(lines)
                prediction = _extract_text(lines)
            except Exception as exc:
                prediction, error = "", f"{type(exc).__name__}: {exc}"
            elapsed = time.perf_counter() - started
            results.append({
                "sample_id": sample_id,
                "engine": engine_name,
                "cer": error_rate(reference, prediction, "characters"),
                "wer": error_rate(reference, prediction, "words"),
                "seconds": round(elapsed, 4),
                "reference": reference,
                "prediction": prediction,
                "error": error,
            })

    summary = []
    for engine_name in engines:
        group = [row for row in results if row["engine"] == engine_name]
        successful = [row for row in group if not row["error"]]
        summary.append({
            "engine": engine_name,
            "samples": len(group),
            "successful_samples": len(successful),
            "failed_samples": len(group) - len(successful),
            "mean_cer": round(sum(r["cer"] for r in group) / len(group), 4) if group else None,
            "mean_wer": round(sum(r["wer"] for r in group) / len(group), 4) if group else None,
            "mean_seconds": round(sum(r["seconds"] for r in group) / len(group), 4) if group else None,
        })

    report = {
        "schema_version": 1,
        "manifest": str(manifest_path),
        "normalization": "NFKC; remove Arabic diacritics and tatweel; collapse whitespace; casefold",
        "metrics_note": "Lower CER/WER is better. Results depend on sample quality and reference transcription.",
        "summary": summary,
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/ocr-report.json"))
    parser.add_argument("--engines", default="tesseract,paddleocr,hybrid",
                        help="Comma-separated: tesseract,paddleocr,hybrid")
    args = parser.parse_args()
    engines = [item.strip() for item in args.engines.split(",") if item.strip()]
    if not engines or any(item not in {"tesseract", "paddleocr", "hybrid"} for item in engines):
        parser.error("--engines must contain tesseract, paddleocr, and/or hybrid")
    try:
        report = run_benchmark(args.manifest, args.output, engines)
    except Exception as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Full report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
