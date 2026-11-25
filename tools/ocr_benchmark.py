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


def summarize_results(results: list[dict], engines: list[str]) -> tuple[list[dict], list[dict]]:
    """Summarize engine performance overall and within each labeled sample category."""
    def metrics(rows: list[dict]) -> dict:
        successful = [row for row in rows if not row.get("error")]
        return {
            "samples": len(rows),
            "successful_samples": len(successful),
            "failed_samples": len(rows) - len(successful),
            "mean_cer": round(sum(r["cer"] for r in rows) / len(rows), 4) if rows else None,
            "mean_wer": round(sum(r["wer"] for r in rows) / len(rows), 4) if rows else None,
            "mean_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 4) if rows else None,
        }

    overall = []
    for engine_name in engines:
        rows = [row for row in results if row["engine"] == engine_name]
        overall.append({"engine": engine_name, **metrics(rows)})

    by_category = []
    categories = sorted({str(row.get("category") or "uncategorized") for row in results})
    for category in categories:
        for engine_name in engines:
            rows = [row for row in results
                    if row["engine"] == engine_name
                    and str(row.get("category") or "uncategorized") == category]
            if rows:
                by_category.append({"category": category, "engine": engine_name, **metrics(rows)})
    return overall, by_category


def _validate_manifest(manifest: dict, manifest_path: Path) -> list[dict]:
    """Validate benchmark entries and confine image reads to the manifest directory."""
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    samples = manifest.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("manifest.samples must contain at least one labeled sample")

    root = manifest_path.resolve().parent
    validated: list[dict] = []
    seen_ids: set[str] = set()
    for index, sample in enumerate(samples, 1):
        if not isinstance(sample, dict):
            raise ValueError(f"samples[{index}] must be an object")
        image_value = sample.get("image")
        if not isinstance(image_value, str) or not image_value.strip():
            raise ValueError(f"samples[{index}].image must be a non-empty relative path")
        image_path = (root / image_value).resolve()
        try:
            image_path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"samples[{index}].image must stay inside the manifest directory") from exc
        if not image_path.is_file():
            raise FileNotFoundError(f"samples[{index}]: image not found: {image_path}")

        reference = sample.get("reference")
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError(f"samples[{index}].reference must contain the exact transcription")
        sample_id = str(sample.get("id") or image_value).strip()
        if not sample_id or sample_id in seen_ids:
            raise ValueError(f"samples[{index}] has an empty or duplicate id")
        seen_ids.add(sample_id)
        validated.append({**sample, "_sample_id": sample_id, "_image_path": image_path})
    return validated


def run_benchmark(manifest_path: Path, output_path: Path, engines: list[str]) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples = _validate_manifest(manifest, manifest_path)

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
        sample_id = sample["_sample_id"]
        image_path = sample["_image_path"]
        reference = sample["reference"]
        language = str(sample.get("language") or manifest.get("language") or "ara")
        category = str(sample.get("category") or "uncategorized").strip() or "uncategorized"
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
                "category": category,
                "engine": engine_name,
                "cer": error_rate(reference, prediction, "characters"),
                "wer": error_rate(reference, prediction, "words"),
                "seconds": round(elapsed, 4),
                "reference": reference,
                "prediction": prediction,
                "error": error,
            })

    summary, category_summary = summarize_results(results, engines)

    report = {
        "schema_version": 1,
        "manifest": str(manifest_path),
        "normalization": "NFKC; remove Arabic diacritics and tatweel; collapse whitespace; casefold",
        "metrics_note": "Lower CER/WER is better. Results depend on sample quality and reference transcription.",
        "summary": summary,
        "category_summary": category_summary,
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
