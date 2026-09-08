#!/usr/bin/env python3
"""Release-quality gates for the Kaggle-facing Korea customs dataset."""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

import hsk_reference


HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]")
HS10_RE = re.compile(r"^\d{10}$")
MEASURES = [
    "export_usd",
    "export_weight_kg",
    "import_usd",
    "import_weight_kg",
    "trade_balance_usd",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bad_unicode_reason(value: str | None) -> str | None:
    if value is None:
        return None
    if "\ufffd" in value:
        return "replacement_character"
    if "\x00" in value:
        return "nul_character"
    if any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        return "control_character"
    try:
        if value.encode("utf-8").decode("utf-8") != value:
            return "utf8_roundtrip_mismatch"
    except UnicodeError:
        return "utf8_encode_error"
    return None


def has_hangul(value: str | None) -> bool:
    return bool(value and HANGUL_RE.search(value))


def check_utf8_text_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        return {"path": str(path), "ok": False, "error": f"utf8_decode_error: {exc}"}
    reason = bad_unicode_reason(text)
    return {"path": str(path), "ok": reason is None, "bytes": path.stat().st_size, "error": reason}


def check_country_reference(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    codes = [str(row.get("country_code") or "").strip() for row in rows]
    names = [str(row.get("country_name_ko") or "").strip() for row in rows]
    bad_unicode = sum(bool(bad_unicode_reason(value)) for value in names)
    no_hangul = sum(bool(value) and not has_hangul(value) for value in names)
    duplicates = len(codes) - len(set(codes))
    missing_names = sum(not value for value in names)
    return {
        "rows": len(rows),
        "unique_country_codes": len(set(codes)),
        "duplicate_country_codes": duplicates,
        "missing_country_name_ko": missing_names,
        "bad_unicode_rows": bad_unicode,
        "korean_name_without_hangul": no_hangul,
        "ok": bool(rows) and duplicates == 0 and missing_names == 0 and bad_unicode == 0 and no_hangul == 0,
    }


def check_hsk_reference(path: Path) -> dict[str, Any]:
    table = pq.ParquetFile(path).read()
    schema_ok = table.schema.equals(hsk_reference.SCHEMA, check_metadata=False)
    rows = table.to_pylist()
    keys = [(int(row["reference_year"]), str(row["hs10"])) for row in rows]
    invalid_hs10 = 0
    prefix_mismatch = 0
    missing_ko = 0
    missing_en = 0
    bad_ko = 0
    bad_en = 0
    no_hangul = 0
    for row in rows:
        hs10 = str(row["hs10"])
        invalid_hs10 += not bool(HS10_RE.fullmatch(hs10))
        prefix_mismatch += bool(
            row["hs8"] != hs10[:8]
            or row["hs6"] != hs10[:6]
            or row["hs4"] != hs10[:4]
            or row["hs2"] != hs10[:2]
        )
        name_ko = str(row.get("name_ko") or "").strip()
        name_en = str(row.get("name_en") or "").strip()
        missing_ko += not bool(name_ko)
        missing_en += not bool(name_en)
        bad_ko += bool(bad_unicode_reason(name_ko))
        bad_en += bool(bad_unicode_reason(name_en))
        no_hangul += bool(name_ko) and not has_hangul(name_ko)
    years = sorted({int(row["reference_year"]) for row in rows})
    duplicates = len(keys) - len(set(keys))
    ok = all(
        [
            schema_ok,
            bool(rows),
            duplicates == 0,
            invalid_hs10 == 0,
            prefix_mismatch == 0,
            missing_ko == 0,
            missing_en == 0,
            bad_ko == 0,
            bad_en == 0,
            no_hangul == 0,
        ]
    )
    return {
        "rows": table.num_rows,
        "bytes": path.stat().st_size,
        "schema_ok": schema_ok,
        "year_min": years[0] if years else None,
        "year_max": years[-1] if years else None,
        "year_count": len(years),
        "duplicate_year_hs10": duplicates,
        "invalid_hs10": invalid_hs10,
        "prefix_mismatch": prefix_mismatch,
        "missing_name_ko": missing_ko,
        "missing_name_en": missing_en,
        "bad_unicode_name_ko": bad_ko,
        "bad_unicode_name_en": bad_en,
        "korean_name_without_hangul": no_hangul,
        "ok": ok,
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_normalization_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "missing": True, "path": str(path)}
    obj = read_json(path)
    verify = obj.get("verification") or {}
    stats = obj.get("normalization_stats") or {}
    row_reconciliation = obj.get("stored_row_reconciliation") or stats.get("stored_row_reconciliation") or {}
    summary_mismatches = int(obj.get("source_summary_mismatches") or stats.get("source_summary_mismatches") or 0)
    summary_checked = int(obj.get("source_summary_checked") or stats.get("source_summary_checked") or 0)
    summary_matches = int(obj.get("source_summary_matches") or stats.get("source_summary_matches") or 0)
    summary_missing = int(obj.get("source_summary_missing") or stats.get("source_summary_missing") or 0)
    rounding_sources = int(
        obj.get("source_summary_weight_rounding_sources")
        or stats.get("source_summary_weight_rounding_sources")
        or 0
    )
    rounding_abs_kg = int(
        obj.get("source_summary_weight_rounding_abs_kg")
        or stats.get("source_summary_weight_rounding_abs_kg")
        or 0
    )
    return {
        "path": str(path),
        "selected_country_months": int(obj.get("selected_country_months") or 0),
        "partition_count": int(stats.get("partition_count") or 0),
        "canonical_rows": int(stats.get("canonical_rows") or 0),
        "non_hs10_rows": int(stats.get("non_hs10_rows") or 0),
        "fatal_anomalies": int(obj.get("fatal_anomalies") or 0),
        "hsk_reference_unknown_rows": int(obj.get("hsk_reference_unknown_rows") or 0),
        "hsk_reference_unknown_unique": int(obj.get("hsk_reference_unknown_unique") or 0),
        "schema_ok": bool(verify.get("schema_ok")),
        "duplicate_keys": int(verify.get("duplicate_keys") or 0),
        "partition_month_mismatches": int(verify.get("partition_month_mismatches") or 0),
        "parquet_rows": int(verify.get("parquet_rows") or 0),
        "parquet_bytes": int(verify.get("parquet_bytes") or 0),
        "source_summary_checked": summary_checked,
        "source_summary_matches": summary_matches,
        "source_summary_mismatches": summary_mismatches,
        "source_summary_missing": summary_missing,
        "source_summary_weight_rounding_sources": rounding_sources,
        "source_summary_weight_rounding_abs_kg": rounding_abs_kg,
        "stored_row_reconciliation_ok": bool(row_reconciliation.get("reconciles")),
        "ok": (
            int(obj.get("selected_country_months") or 0) > 0
            and int(stats.get("partition_count") or 0) > 0
            and bool(verify.get("schema_ok"))
            and int(verify.get("duplicate_keys") or 0) == 0
            and int(verify.get("partition_month_mismatches") or 0) == 0
            and int(obj.get("fatal_anomalies") or 0) == 0
            and int(verify.get("parquet_rows") or 0) == int(stats.get("canonical_rows") or 0)
            and summary_mismatches == 0
            and bool(row_reconciliation.get("reconciles"))
        ),
    }


def check_derived_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "missing": True, "path": str(path)}
    obj = read_json(path)
    levels = [int(value) for value in obj.get("levels") or []]
    stats = obj.get("stats") or {}
    totals = stats.get("totals") or {}
    residual_totals = stats.get("residual_totals") or {}
    level_stats = stats.get("levels") or {}
    reconciliation_failures = 0
    for level in levels:
        key = str(level)
        if key not in level_stats or f"hs{level}" not in totals:
            reconciliation_failures += 1
            continue
        expected = {
            measure: int((totals.get("hs10") or {}).get(measure) or 0)
            + int((residual_totals.get(key) or {}).get(measure) or 0)
            for measure in MEASURES
        }
        actual = {measure: int((totals[f"hs{level}"]).get(measure) or 0) for measure in MEASURES}
        if actual != expected:
            reconciliation_failures += 1
    required = {2, 4, 6, 8}
    required_present = required.issubset(set(levels))
    return {
        "path": str(path),
        "levels": levels,
        "input_rows": int(stats.get("input_rows") or 0),
        "residual_input_rows": int(stats.get("residual_input_rows") or 0),
        "reconciliation_failures": reconciliation_failures,
        "required_levels_present": required_present,
        "ok": bool(stats.get("input_rows")) and required_present and reconciliation_failures == 0,
    }


def check_anomaly_text(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "missing": True, "path": str(path)}
    table = pq.ParquetFile(path).read(columns=["reason", "name_ko"])
    bad = 0
    no_hangul = 0
    non_hs10_rows = 0
    negative_weight_rows = 0
    for row in table.to_pylist():
        if row.get("reason") == "non_hs10_code":
            non_hs10_rows += 1
        if row.get("reason") == "negative_weight":
            negative_weight_rows += 1
        name = row.get("name_ko")
        bad += bool(bad_unicode_reason(name))
        no_hangul += bool(name) and not has_hangul(name)
    return {
        "rows": table.num_rows,
        "non_hs10_rows": non_hs10_rows,
        "negative_weight_rows": negative_weight_rows,
        "bad_unicode_name_ko": bad,
        "korean_name_without_hangul": no_hangul,
        "ok": bad == 0,
    }


def write_coverage_report(path: Path, report: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []
    for section, values in report["checks"].items():
        if not isinstance(values, dict):
            continue
        for metric, value in values.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                rows.append({"section": section, "metric": metric, "value": value})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["section", "metric", "value"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Kaggle release-quality checks")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--output-dir", default="data/audits/release_qa")
    args = ap.parse_args()

    data_dir = Path(args.data_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    repo_root = data_dir.parent
    checks: dict[str, Any] = {
        "country_reference": check_country_reference(data_dir / "reference" / "country_reference.csv"),
        "hsk_reference": check_hsk_reference(data_dir / "reference" / "hsk_code_reference.parquet"),
        "normalization": check_normalization_manifest(
            data_dir / "audits" / "normalization" / "normalization_manifest.json"
        ),
        "derivation": check_derived_manifest(data_dir / "audits" / "derivation" / "derivation_manifest.json"),
        "anomaly_text": check_anomaly_text(
            data_dir / "audits" / "normalization" / "normalization_anomalies.parquet"
        ),
    }
    for name in ["README.md", "README.ko.md", "DATA_MODEL.md", "DATA_MODEL.ko.md", "PROJECT_STATUS.md"]:
        checks[f"text:{name}"] = check_utf8_text_file(repo_root / name)

    fatal_sections = [name for name, result in checks.items() if isinstance(result, dict) and not result.get("ok")]
    warnings: list[str] = []
    anomaly = checks["anomaly_text"]
    if int(anomaly.get("korean_name_without_hangul") or 0):
        warnings.append(
            f"source anomaly names without Hangul: {anomaly['korean_name_without_hangul']} (preserved, not rewritten)"
        )
    if int(anomaly.get("negative_weight_rows") or 0):
        warnings.append(
            f"source rows with negative reported weight: {anomaly['negative_weight_rows']} "
            "(preserved exactly and exposed in the anomaly audit)"
        )
    normalization = checks["normalization"]
    if int(normalization.get("hsk_reference_unknown_unique") or 0):
        warnings.append(
            "some canonical HSK10 facts are absent from the annual CLIP reference; they remain canonical with null "
            "hs_revision and are audited rather than dropped"
        )

    report = {
        "generated_at": utc_now(),
        "goal": "Kaggle Usability 10.00 and dataset medal without over-cleaning official source data",
        "checks": checks,
        "fatal_sections": fatal_sections,
        "warnings": warnings,
        "release_gate_pass": not fatal_sections,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "release_qa.json"
    coverage_path = output_dir / "coverage_report.csv"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_coverage_report(coverage_path, report)
    print(f"release_gate_pass={report['release_gate_pass']}")
    print(f"fatal_sections={len(fatal_sections)}")
    print(f"warnings={len(warnings)}")
    print(f"report={report_path}")
    print(f"coverage={coverage_path}")
    return 0 if report["release_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
