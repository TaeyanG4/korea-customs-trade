#!/usr/bin/env python3
"""Build the analyst-facing Kaggle release package.

This script never re-collects or reinterprets source data. It packages the
already validated Stage-11 outputs into one file per analytical grain, adds
small audit/reference files, and emits Kaggle dataset metadata with file and
column descriptions.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq


FACT_INPUTS = {
    "trade_hs10_monthly.parquet": Path("data/normalized/hs10"),
    "trade_hs8_monthly.parquet": Path("data/derived/hs8"),
    "trade_hs6_monthly.parquet": Path("data/derived/hs6"),
    "trade_hs4_monthly.parquet": Path("data/derived/hs4"),
    "trade_hs2_monthly.parquet": Path("data/derived/hs2"),
}

REFERENCE_FILES = {
    "hsk_code_reference.parquet": Path("data/reference/hsk_code_reference.parquet"),
    "country_reference.csv": Path("data/reference/country_reference.csv"),
    "hsk_reference_gaps.csv": Path("data/audits/normalization/hsk_reference_unknown_codes.csv"),
    "coverage_report.csv": Path("data/audits/release_qa/coverage_report.csv"),
}

DOC_FILES = [
    "DATA_DICTIONARY.md",
    "METHODOLOGY.md",
    "SOURCES.md",
]

COMMON_FACT_DESCRIPTIONS = {
    "month": "Trade month in YYYYMM format.",
    "country_code": "Korea Customs Service partner country/territory code.",
    "hs10": "Exact numeric 10-digit Korean HSK code returned by the source API.",
    "hs8": "First 8 digits of HSK10; Korean national-detail prefix, not an international HS level.",
    "hs6": "First 6 digits of HSK10; international HS subheading level.",
    "hs4": "First 4 digits of HSK10; international HS heading level.",
    "hs2": "First 2 digits of HSK10; international HS chapter level.",
    "export_usd": "Export value in USD. Korea Customs publishes exports on an FOB basis.",
    "export_weight_kg": "Reported export net weight in kilograms. Rare negative source values are preserved and audited.",
    "import_usd": "Import value in USD. Korea Customs publishes imports on a CIF/customs-value basis.",
    "import_weight_kg": "Reported import net weight in kilograms. Rare negative source values are preserved and audited.",
    "trade_balance_usd": "export_usd minus import_usd.",
    "hs_revision": "Official annual KCS CLIP edition label (HSK-YYYY) when the annual reference contains the code; otherwise null.",
    "residual_export_usd": "Contribution from safely mappable non-HSK10 source rows included in export_usd.",
    "residual_export_weight_kg": "Contribution from safely mappable non-HSK10 source rows included in export_weight_kg.",
    "residual_import_usd": "Contribution from safely mappable non-HSK10 source rows included in import_usd.",
    "residual_import_weight_kg": "Contribution from safely mappable non-HSK10 source rows included in import_weight_kg.",
    "residual_trade_balance_usd": "Contribution from safely mappable non-HSK10 source rows included in trade_balance_usd.",
    "source_row_count": "Number of HSK10 fact rows plus safely mapped residual source rows contributing to this aggregate row.",
    "exception_row_count": "Number of non-HSK10 source exception rows contributing to this aggregate row.",
    "has_residual": "True when at least one non-HSK10 source exception contributes to this aggregate row.",
}

HSK_REFERENCE_DESCRIPTIONS = {
    "reference_year": "Annual Korea Customs CLIP reference edition year.",
    "hs_revision": "Annual edition label HSK-YYYY.",
    "valid_from": "Reference validity start recorded by the annual collector; annual-edition semantics only.",
    "valid_to": "Reference validity end recorded by the annual collector; annual-edition semantics only.",
    "clip_sct_year": "CLIP tariff-table year value returned by the official source.",
    "clip_hstd_year": "CLIP HS standard year value returned by the official source.",
    "hs10": COMMON_FACT_DESCRIPTIONS["hs10"],
    "hs8": COMMON_FACT_DESCRIPTIONS["hs8"],
    "hs6": COMMON_FACT_DESCRIPTIONS["hs6"],
    "hs4": COMMON_FACT_DESCRIPTIONS["hs4"],
    "hs2": COMMON_FACT_DESCRIPTIONS["hs2"],
    "name_ko": "Official Korean item name from the KCS CLIP annual tariff table.",
    "name_en": "Official English item name from the KCS CLIP annual tariff table.",
    "source": "Reference source identifier.",
    "source_url": "Official source URL used to build the annual reference.",
}

COUNTRY_DESCRIPTIONS = {
    "country_code": "Korea Customs Service collection code used by the trade API.",
    "country_name_ko": "Korean country/territory name from the official KCS lookup workbook.",
    "country_name_en": "English name from UN M49 only when the KCS code exactly matches a current UN alpha-2 code.",
    "un_m49": "UN M49 numeric code when an exact current match exists; blank otherwise.",
    "iso_alpha3": "ISO alpha-3 code from UN M49 when an exact current match exists; blank otherwise.",
    "un_match_status": "Whether the KCS code matched UN M49 exactly.",
    "kcs_source_version": "Version identifier of the official KCS lookup workbook.",
    "kcs_source_row": "Source-row number in the KCS workbook for reproducibility.",
}

ANOMALY_DESCRIPTIONS = {
    "reason": "Source anomaly category.",
    "month": COMMON_FACT_DESCRIPTIONS["month"],
    "country_code": COMMON_FACT_DESCRIPTIONS["country_code"],
    "country_code_raw": "Country code as returned in the source row.",
    "raw_hs_code": "HS code exactly as returned by the source API.",
    "raw_hs_length": "Character length of raw_hs_code.",
    "name_ko": "Korean item name returned in the source API row, preserved without cosmetic rewriting.",
    "export_usd": COMMON_FACT_DESCRIPTIONS["export_usd"],
    "export_weight_kg": COMMON_FACT_DESCRIPTIONS["export_weight_kg"],
    "import_usd": COMMON_FACT_DESCRIPTIONS["import_usd"],
    "import_weight_kg": COMMON_FACT_DESCRIPTIONS["import_weight_kg"],
    "trade_balance_usd": COMMON_FACT_DESCRIPTIONS["trade_balance_usd"],
    "source_finished_at": "UTC timestamp of the successful source request used for this row.",
}

HSK_GAP_DESCRIPTIONS = {
    "reference_year": "Annual KCS CLIP edition year used for matching.",
    "hs10": COMMON_FACT_DESCRIPTIONS["hs10"],
    "fact_rows": "Number of canonical trade fact rows observed for this year/code combination.",
    "months": "Comma-separated YYYYMM months in which the code was observed.",
    "name_ko_variants": "Korean source-name variants observed in the trade API for this year/code.",
}

COVERAGE_DESCRIPTIONS = {
    "section": "QA section name.",
    "metric": "QA metric name.",
    "value": "Recorded QA metric value.",
}

FILE_DESCRIPTIONS = {
    "trade_hs10_monthly.parquet": "Canonical monthly trade facts at strict numeric 10-digit Korean HSK grain. This is the source-of-truth analytical fact table.",
    "trade_hs8_monthly.parquet": "Monthly HS8-prefix aggregate derived from strict HSK10. Residuals are included only when a source exception has at least 8 valid digits.",
    "trade_hs6_monthly.parquet": "Recommended general-purpose monthly table at international HS6 level. Safely mappable non-HSK10 residuals are included and explicitly quantified.",
    "trade_hs4_monthly.parquet": "Monthly international HS4 heading-level aggregate with residual audit columns.",
    "trade_hs2_monthly.parquet": "Monthly international HS2 chapter-level aggregate with residual audit columns.",
    "trade_hs6_202607_sample.csv": "Convenience CSV containing the complete HS6 table for the latest release month (2026-07) so Kaggle users can preview and start quickly without loading the full history.",
    "hsk_code_reference.parquet": "Official annual 2012-2026 Korean HSK code reference built from Korea Customs Service CLIP, including Korean and English item names.",
    "country_reference.csv": "Official KCS partner-code reference enriched only by exact UN M49 matches.",
    "source_code_exceptions.parquet": "Rare non-HSK10 source rows preserved exactly rather than padded or guessed into HSK10.",
    "source_weight_warnings.parquet": "Rare source rows with negative reported weight. Values are preserved exactly and are not clamped to zero.",
    "hsk_reference_gaps.csv": "Annual HSK10 codes observed in trade facts but absent from the same-year CLIP reference. Facts remain present with null hs_revision.",
    "coverage_report.csv": "Machine-readable Stage-11 release QA metrics and pass/fail coverage checks.",
    "release_manifest.json": "Release inventory with file row counts, byte sizes, SHA-256 hashes, source coverage, and QA summary.",
    "DATA_DICTIONARY.md": "Human-readable field definitions and grain semantics.",
    "METHODOLOGY.md": "Collection, normalization, residual, revision, reconciliation, and update methodology.",
    "SOURCES.md": "Official data sources, provenance, and reuse notes.",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def parquet_files(root: Path) -> list[Path]:
    files = sorted(root.glob("year=*/mm=*/part-*.parquet"))
    if not files:
        raise RuntimeError(f"no monthly parquet files found under {root}")
    return files


def consolidate_parquet(root: Path, output: Path) -> dict[str, Any]:
    """Stream monthly Parquet files into one release Parquet without full-memory load."""
    inputs = parquet_files(root)
    first = pq.ParquetFile(inputs[0])
    schema = first.schema_arrow
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    input_bytes = 0
    writer = pq.ParquetWriter(
        output,
        schema,
        compression="zstd",
        compression_level=6,
        use_dictionary=True,
        write_statistics=True,
        version="2.6",
    )
    try:
        for index, path in enumerate(inputs, 1):
            pf = pq.ParquetFile(path)
            if not pf.schema_arrow.equals(schema, check_metadata=False):
                raise RuntimeError(f"schema mismatch while packaging: {path}")
            input_bytes += path.stat().st_size
            for batch in pf.iter_batches(batch_size=100_000):
                table = pa.Table.from_batches([batch], schema=schema)
                writer.write_table(table, row_group_size=table.num_rows)
                rows += table.num_rows
            if index % 25 == 0 or index == len(inputs):
                print(f"packaging {output.name}: files={index}/{len(inputs)} rows={rows}", flush=True)
    finally:
        writer.close()
    check = pq.ParquetFile(output)
    if check.metadata.num_rows != rows:
        raise RuntimeError(f"row mismatch after packaging {output}: {check.metadata.num_rows} != {rows}")
    return {
        "rows": rows,
        "source_files": len(inputs),
        "source_bytes": input_bytes,
        "bytes": output.stat().st_size,
        "sha256": sha256_file(output),
        "columns": schema.names,
    }


def release_anomaly_table(source: Path, reason: str) -> pa.Table:
    table = pq.ParquetFile(source).read()
    reason_values = table["reason"].to_pylist()
    mask = pa.array([value == reason for value in reason_values], type=pa.bool_())
    filtered = table.filter(mask)
    selected = filtered.select(
        [
            "reason",
            "month",
            "requested_country",
            "country_code_raw",
            "hs_code_raw",
            "hs_length",
            "name_ko",
            "export_usd",
            "export_weight_kg",
            "import_usd",
            "import_weight_kg",
            "trade_balance_usd",
            "source_finished_at",
        ]
    )
    return selected.rename_columns(
        [
            "reason",
            "month",
            "country_code",
            "country_code_raw",
            "raw_hs_code",
            "raw_hs_length",
            "name_ko",
            "export_usd",
            "export_weight_kg",
            "import_usd",
            "import_weight_kg",
            "trade_balance_usd",
            "source_finished_at",
        ]
    )


def write_anomaly_release(source: Path, output: Path, reason: str) -> dict[str, Any]:
    table = release_anomaly_table(source, reason)
    pq.write_table(table, output, compression="zstd", compression_level=6, use_dictionary=True)
    return {
        "rows": table.num_rows,
        "bytes": output.stat().st_size,
        "sha256": sha256_file(output),
        "columns": table.schema.names,
    }


def csv_info(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = sum(1 for _ in reader)
    return {
        "rows": rows,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "columns": header,
    }


def copy_with_info(source: Path, output: Path) -> dict[str, Any]:
    if not source.exists():
        raise RuntimeError(f"required release source missing: {source}")
    shutil.copy2(source, output)
    if output.suffix.lower() == ".parquet":
        pf = pq.ParquetFile(output)
        return {
            "rows": pf.metadata.num_rows,
            "bytes": output.stat().st_size,
            "sha256": sha256_file(output),
            "columns": pf.schema_arrow.names,
        }
    if output.suffix.lower() == ".csv":
        return csv_info(output)
    return {"bytes": output.stat().st_size, "sha256": sha256_file(output)}


def write_latest_hs6_sample(source: Path, output: Path, month: str = "202607") -> dict[str, Any]:
    year, mm = month[:4], month[4:]
    part = source / f"year={year}" / f"mm={mm}" / "part-00000.parquet"
    if not part.exists():
        raise RuntimeError(f"latest-month HS6 sample source missing: {part}")
    table = pq.ParquetFile(part).read()
    pacsv.write_csv(table, output)
    info = csv_info(output)
    if info["rows"] != table.num_rows:
        raise RuntimeError("HS6 sample CSV row count mismatch")
    return info


def arrow_type_to_kaggle(field: pa.Field) -> str:
    typ = field.type
    if pa.types.is_boolean(typ):
        return "boolean"
    if pa.types.is_integer(typ):
        return "integer"
    if pa.types.is_floating(typ) or pa.types.is_decimal(typ):
        return "numeric"
    if pa.types.is_timestamp(typ) or pa.types.is_date(typ):
        return "datetime"
    return "string"


def fields_for_schema(schema: pa.Schema, descriptions: dict[str, str]) -> list[dict[str, str]]:
    return [
        {
            "name": field.name,
            "description": descriptions.get(field.name, field.name),
            "type": arrow_type_to_kaggle(field),
        }
        for field in schema
    ]


def fields_for_csv(path: Path, descriptions: dict[str, str]) -> list[dict[str, str]]:
    schema = pacsv.read_csv(path).schema
    return fields_for_schema(schema, descriptions)


def resource_schema(path: Path) -> list[dict[str, str]] | None:
    name = path.name
    if name.startswith("trade_hs") and path.suffix == ".parquet":
        return fields_for_schema(pq.ParquetFile(path).schema_arrow, COMMON_FACT_DESCRIPTIONS)
    if name == "trade_hs6_202607_sample.csv":
        return fields_for_csv(path, COMMON_FACT_DESCRIPTIONS)
    if name == "hsk_code_reference.parquet":
        return fields_for_schema(pq.ParquetFile(path).schema_arrow, HSK_REFERENCE_DESCRIPTIONS)
    if name == "country_reference.csv":
        return fields_for_csv(path, COUNTRY_DESCRIPTIONS)
    if name in {"source_code_exceptions.parquet", "source_weight_warnings.parquet"}:
        return fields_for_schema(pq.ParquetFile(path).schema_arrow, ANOMALY_DESCRIPTIONS)
    if name == "hsk_reference_gaps.csv":
        return fields_for_csv(path, HSK_GAP_DESCRIPTIONS)
    if name == "coverage_report.csv":
        return fields_for_csv(path, COVERAGE_DESCRIPTIONS)
    return None


def dataset_description(repo_root: Path) -> str:
    return (repo_root / "KAGGLE_DESCRIPTION.md").read_text(encoding="utf-8")


def build_kaggle_metadata(output: Path, repo_root: Path) -> dict[str, Any]:
    resources = []
    for path in sorted(output.iterdir(), key=lambda p: p.name.lower()):
        if path.name in {"dataset-metadata.json", "dataset-cover-image.jpg"}:
            continue
        if not path.is_file():
            continue
        resource: dict[str, Any] = {
            "path": path.name,
            "description": FILE_DESCRIPTIONS.get(path.name, f"Release file: {path.name}"),
        }
        fields = resource_schema(path)
        if fields:
            resource["schema"] = {"fields": fields}
        resources.append(resource)
    metadata = {
        "title": "South Korea Customs Trade 2012-2026 HSK10",
        "subtitle": "Monthly trade by 269 partners and 10-digit Korean HSK products",
        "description": dataset_description(repo_root),
        "id": "taeyangg4/south-korea-customs-trade-hsk10",
        "licenses": [{"name": "other"}],
        "resources": resources,
        "keywords": ["economics", "international trade", "time series", "tabular", "asia"],
        "expectedUpdateFrequency": "monthly",
        "userSpecifiedSources": (
            "Korea Customs Service via the Korea Public Data Portal (data.go.kr) and the official KCS CLIP tariff tables. "
            "The source API is listed with 이용허락범위 제한 없음 (no restriction on scope of use). See SOURCES.md for provenance and caveats."
        ),
        "image": "dataset-cover-image.jpg",
    }
    (output / "dataset-metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def require_release_qa(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "audits" / "release_qa" / "release_qa.json"
    if not path.exists():
        raise RuntimeError(f"release QA report missing: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    if not report.get("release_gate_pass"):
        raise RuntimeError("Stage-11 release QA has not passed")
    return report


def build_release(repo_root: Path, output: Path, overwrite: bool) -> dict[str, Any]:
    data_dir = repo_root / "data"
    qa = require_release_qa(data_dir)
    staging = output.with_name(output.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    if output.exists() and not overwrite:
        raise RuntimeError(f"release output exists; pass --overwrite: {output}")
    staging.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    file_stats: dict[str, dict[str, Any]] = {}

    for name, relative_root in FACT_INPUTS.items():
        file_stats[name] = consolidate_parquet(repo_root / relative_root, staging / name)

    sample_name = "trade_hs6_202607_sample.csv"
    file_stats[sample_name] = write_latest_hs6_sample(
        repo_root / FACT_INPUTS["trade_hs6_monthly.parquet"], staging / sample_name
    )

    for name, relative in REFERENCE_FILES.items():
        file_stats[name] = copy_with_info(repo_root / relative, staging / name)

    anomalies = data_dir / "audits" / "normalization" / "normalization_anomalies.parquet"
    file_stats["source_code_exceptions.parquet"] = write_anomaly_release(
        anomalies, staging / "source_code_exceptions.parquet", "non_hs10_code"
    )
    file_stats["source_weight_warnings.parquet"] = write_anomaly_release(
        anomalies, staging / "source_weight_warnings.parquet", "negative_weight"
    )

    for doc in DOC_FILES:
        file_stats[doc] = copy_with_info(repo_root / doc, staging / doc)

    cover = repo_root / "assets" / "korea_customs_trade_kaggle_banner.jpg"
    shutil.copy2(cover, staging / "dataset-cover-image.jpg")

    normalization = json.loads(
        (data_dir / "audits" / "normalization" / "normalization_manifest.json").read_text(encoding="utf-8")
    )
    derivation = json.loads(
        (data_dir / "audits" / "derivation" / "derivation_manifest.json").read_text(encoding="utf-8")
    )
    hsk_ref = pq.ParquetFile(data_dir / "reference" / "hsk_code_reference.parquet")

    manifest = {
        "release_generated_at": utc_now(),
        "dataset_title": "South Korea Customs Trade 2012-2026 HSK10",
        "coverage": {
            "start_month": "201201",
            "end_month": "202607",
            "partner_codes": 269,
            "country_month_assignments": int(normalization["selected_country_months"]),
            "source_fact_rows": int(normalization["normalization_stats"]["assigned_fact_rows"]),
            "canonical_hsk10_rows": int(normalization["normalization_stats"]["canonical_rows"]),
            "non_hsk10_source_rows": int(normalization["normalization_stats"]["non_hs10_rows"]),
            "negative_weight_warning_rows": int(normalization["normalization_stats"].get("negative_weight_rows") or 0),
            "hsk_reference_unknown_fact_rows": int(normalization["hsk_reference_unknown_rows"]),
            "hsk_reference_unknown_unique_year_codes": int(normalization["hsk_reference_unknown_unique"]),
            "annual_hsk_reference_rows": int(hsk_ref.metadata.num_rows),
        },
        "quality": {
            "release_gate_pass": bool(qa["release_gate_pass"]),
            "fatal_sections": qa["fatal_sections"],
            "warnings": qa["warnings"],
            "duplicate_hsk10_keys": int(normalization["verification"]["duplicate_keys"]),
            "partition_month_mismatches": int(normalization["verification"]["partition_month_mismatches"]),
            "source_summary_checked": int(normalization["source_summary_checked"]),
            "source_summary_matches": int(normalization["source_summary_matches"]),
            "source_summary_mismatches": int(normalization["source_summary_mismatches"]),
            "stored_row_reconciliation": normalization["stored_row_reconciliation"],
        },
        "derived_levels": derivation["levels"],
        "files": file_stats,
        "build_elapsed_seconds": round(time.monotonic() - t0, 3),
    }
    manifest_path = staging / "release_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    build_kaggle_metadata(staging, repo_root)

    # Final text integrity gate for all upload-facing text-like files.
    for path in staging.iterdir():
        if path.suffix.lower() not in {".md", ".json", ".csv"}:
            continue
        path.read_text(encoding="utf-8")
        if "\ufffd" in path.read_text(encoding="utf-8"):
            raise RuntimeError(f"replacement character found in release text file: {path.name}")

    if output.exists():
        backup = output.with_name(output.name + ".previous")
        if backup.exists():
            shutil.rmtree(backup)
        output.rename(backup)
        staging.rename(output)
        shutil.rmtree(backup)
    else:
        staging.rename(output)
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Kaggle release package from Stage-11 outputs")
    ap.add_argument("--output", default="release/kaggle")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    repo_root = Path(__file__).resolve().parent
    output = (repo_root / args.output).resolve()
    manifest = build_release(repo_root, output, args.overwrite)
    print(f"release_dir={output}")
    print(f"release_gate_pass={manifest['quality']['release_gate_pass']}")
    print(f"canonical_hsk10_rows={manifest['coverage']['canonical_hsk10_rows']}")
    print(f"files={len(manifest['files']) + 2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
