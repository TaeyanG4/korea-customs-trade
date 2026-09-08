#!/usr/bin/env python3
"""Normalize selected Korea Customs raw XML into strict HSK10 Parquet.

Source selection is revision-safe: for each (country, month), exactly one latest
successful request manifest is selected. Older overlapping raw responses are
ignored, so monthly refreshes can add, change, or remove facts without creating
duplicates in the normalized dataset.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.parquet as pq

import pilot


MEASURES = [
    "export_usd",
    "export_weight_kg",
    "import_usd",
    "import_weight_kg",
    "trade_balance_usd",
]
XML_MEASURE_FIELDS = {
    "export_usd": "expDlr",
    "export_weight_kg": "expWgt",
    "import_usd": "impDlr",
    "import_weight_kg": "impWgt",
    "trade_balance_usd": "balPayments",
}


SCHEMA = pa.schema(
    [
        pa.field("month", pa.string(), nullable=False),
        pa.field("country_code", pa.string(), nullable=False),
        pa.field("hs10", pa.string(), nullable=False),
        pa.field("hs8", pa.string(), nullable=False),
        pa.field("hs6", pa.string(), nullable=False),
        pa.field("hs4", pa.string(), nullable=False),
        pa.field("hs2", pa.string(), nullable=False),
        pa.field("export_usd", pa.int64(), nullable=False),
        pa.field("export_weight_kg", pa.int64(), nullable=False),
        pa.field("import_usd", pa.int64(), nullable=False),
        pa.field("import_weight_kg", pa.int64(), nullable=False),
        pa.field("trade_balance_usd", pa.int64(), nullable=False),
        pa.field("hs_revision", pa.string(), nullable=True),
    ],
    metadata={
        b"dataset": b"South Korea Customs Trade - strict HSK10 facts",
        b"month_format": b"YYYYMM",
        b"hs_revision_note": b"official annual KCS CLIP HSK edition when the code is present; otherwise null",
    },
)

ANOMALY_SCHEMA = pa.schema(
    [
        pa.field("reason", pa.string(), nullable=False),
        pa.field("month", pa.string(), nullable=False),
        pa.field("requested_country", pa.string(), nullable=False),
        pa.field("country_code_raw", pa.string(), nullable=True),
        pa.field("hs_code_raw", pa.string(), nullable=True),
        pa.field("hs_length", pa.int64(), nullable=False),
        pa.field("name_ko", pa.string(), nullable=True),
        pa.field("export_usd", pa.int64(), nullable=True),
        pa.field("export_weight_kg", pa.int64(), nullable=True),
        pa.field("import_usd", pa.int64(), nullable=True),
        pa.field("import_weight_kg", pa.int64(), nullable=True),
        pa.field("trade_balance_usd", pa.int64(), nullable=True),
        pa.field("source_manifest", pa.string(), nullable=False),
        pa.field("source_raw_path", pa.string(), nullable=False),
        pa.field("source_finished_at", pa.string(), nullable=True),
    ]
)


@dataclass(frozen=True)
class SourceManifest:
    manifest_path: Path
    raw_path: Path
    country: str
    window_start: str
    window_end: str
    requested_at: str
    finished_at: str
    selection_timestamp: float

    @property
    def window(self) -> pilot.Window:
        return pilot.Window(self.window_start, self.window_end)

    @property
    def span_months(self) -> int:
        return len(pilot.months_in_window(self.window))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_timestamp(value: str | None, fallback: float) -> float:
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


def raw_path_for_manifest(data_dir: Path, country: str, window_start: str, window_end: str) -> Path:
    year = window_start[:4]
    return (
        data_dir
        / "raw"
        / f"year={year}"
        / f"country={country}"
        / f"response_{window_start}-{window_end}.xml.gz"
    )


def load_country_reference(path: Path) -> set[str]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    codes = {r["country_code"].strip().upper() for r in rows}
    if not codes:
        raise RuntimeError("country reference is empty")
    return codes


def load_hsk_revision_map(path: Path) -> dict[int, dict[str, str]]:
    """Load the official annual HSK reference as year -> HSK10 -> revision.

    A missing code is not treated as a normalization failure. Trade rows can
    legitimately expose sub-annual source/revision edge cases that are not
    represented by CLIP's annual selector, so unknown codes remain canonical
    facts with a null ``hs_revision`` and are audited separately.
    """
    if not path.exists():
        raise RuntimeError(f"HSK reference not found: {path}")
    table = pq.ParquetFile(path).read(columns=["reference_year", "hs10", "hs_revision"])
    revisions: dict[int, dict[str, str]] = defaultdict(dict)
    for row in table.to_pylist():
        year = int(row["reference_year"])
        hs10 = str(row["hs10"])
        revision = str(row["hs_revision"])
        existing = revisions[year].get(hs10)
        if existing is not None and existing != revision:
            raise RuntimeError(f"conflicting HSK revision for {year}/{hs10}: {existing} vs {revision}")
        revisions[year][hs10] = revision
    if not revisions:
        raise RuntimeError("HSK reference is empty")
    return dict(revisions)


def discover_successful_sources(
    data_dir: Path,
    official_codes: set[str],
) -> tuple[list[SourceManifest], list[dict[str, str]]]:
    manifest_root = data_dir / "audits" / "manifests"
    sources: list[SourceManifest] = []
    missing_raw: list[dict[str, str]] = []
    for path in sorted(manifest_root.glob("year=*/country=*/request_*.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if obj.get("success") is not True or obj.get("status") != "success":
            continue
        country = str(obj.get("country") or "").upper()
        start = str(obj.get("window_start") or "")
        end = str(obj.get("window_end") or "")
        if country not in official_codes:
            raise RuntimeError(f"successful manifest contains non-reference country: {country} ({path})")
        if len(start) != 6 or len(end) != 6:
            raise RuntimeError(f"invalid manifest window: {path}")
        raw = raw_path_for_manifest(data_dir, country, start, end)
        if not raw.exists():
            missing_raw.append(
                {"manifest_path": str(path), "raw_path": str(raw), "country": country, "window": f"{start}-{end}"}
            )
            continue
        fallback = path.stat().st_mtime
        requested_at = str(obj.get("requested_at") or "")
        finished_at = str(obj.get("finished_at") or "")
        selection_ts = parse_timestamp(finished_at or requested_at, fallback)
        sources.append(
            SourceManifest(
                manifest_path=path,
                raw_path=raw,
                country=country,
                window_start=start,
                window_end=end,
                requested_at=requested_at,
                finished_at=finished_at,
                selection_timestamp=selection_ts,
            )
        )
    return sources, missing_raw


def intersect_months(window: pilot.Window, start_month: str | None, end_month: str | None) -> list[str]:
    months = pilot.months_in_window(window)
    if start_month:
        months = [m for m in months if m >= start_month]
    if end_month:
        months = [m for m in months if m <= end_month]
    return months


def source_priority(source: SourceManifest) -> tuple[float, int, str]:
    # Newer retrieval wins. If retrieval timestamps tie, prefer the narrower
    # request window (e.g. refresh over annual backfill), then manifest path.
    return (source.selection_timestamp, -source.span_months, str(source.manifest_path))


def select_sources_by_country_month(
    sources: Iterable[SourceManifest],
    start_month: str | None = None,
    end_month: str | None = None,
) -> tuple[dict[tuple[str, str], SourceManifest], dict[tuple[str, str], int]]:
    candidates: dict[tuple[str, str], list[SourceManifest]] = defaultdict(list)
    for source in sources:
        for month in intersect_months(source.window, start_month, end_month):
            candidates[(source.country, month)].append(source)
    selected: dict[tuple[str, str], SourceManifest] = {}
    candidate_counts: dict[tuple[str, str], int] = {}
    for key, vals in candidates.items():
        selected[key] = max(vals, key=source_priority)
        candidate_counts[key] = len(vals)
    return selected, candidate_counts


def selected_assignments(
    selected: dict[tuple[str, str], SourceManifest]
) -> dict[str, dict[Path, tuple[SourceManifest, set[str]]]]:
    by_year: dict[str, dict[Path, tuple[SourceManifest, set[str]]]] = defaultdict(dict)
    for (country, month), source in sorted(selected.items()):
        year = month[:4]
        existing = by_year[year].get(source.manifest_path)
        if existing is None:
            by_year[year][source.manifest_path] = (source, {month})
        else:
            existing[1].add(month)
    return by_year


def write_source_selection_audit(
    path: Path,
    selected: dict[tuple[str, str], SourceManifest],
    candidate_counts: dict[tuple[str, str], int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "country_code",
        "month",
        "candidate_count",
        "selected_window_start",
        "selected_window_end",
        "requested_at",
        "finished_at",
        "manifest_path",
        "raw_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for key in sorted(selected):
            country, month = key
            source = selected[key]
            w.writerow(
                {
                    "country_code": country,
                    "month": month,
                    "candidate_count": candidate_counts[key],
                    "selected_window_start": source.window_start,
                    "selected_window_end": source.window_end,
                    "requested_at": source.requested_at,
                    "finished_at": source.finished_at,
                    "manifest_path": str(source.manifest_path),
                    "raw_path": str(source.raw_path),
                }
            )


def as_required_int(elem: ET.Element, name: str) -> int:
    value = pilot.as_int(pilot.safe_text(elem, name))
    if value is None:
        raise ValueError(f"missing/invalid numeric field {name}")
    return value


def measure_values(elem: ET.Element) -> dict[str, int] | None:
    values: dict[str, int] = {}
    for canonical, xml_name in XML_MEASURE_FIELDS.items():
        value = pilot.as_int(pilot.safe_text(elem, xml_name))
        if value is None:
            return None
        values[canonical] = value
    return values


def classify_summary_differences(
    fact_totals: dict[str, int],
    summary_totals: dict[str, int],
    fact_rows: int,
) -> tuple[dict[str, int], dict[str, int]]:
    """Split raw-summary differences into fatal and accepted rounding deltas.

    Monetary fields and trade balance must match exactly. Detailed weights are
    published as integer kilograms, so summing row-level rounded values can
    differ slightly from the response-level total. A conservative upper bound
    of one kilogram per detailed fact row is accepted and fully audited.
    """
    fatal: dict[str, int] = {}
    accepted_rounding: dict[str, int] = {}
    weight_tolerance = max(1, fact_rows)
    for measure in MEASURES:
        difference = fact_totals[measure] - summary_totals[measure]
        if difference == 0:
            continue
        if measure in {"export_weight_kg", "import_weight_kg"} and abs(difference) <= weight_tolerance:
            accepted_rounding[measure] = difference
        else:
            fatal[measure] = difference
    return fatal, accepted_rounding


def canonical_row(
    elem: ET.Element,
    country: str,
    month: str,
    hs: str,
    hs_revision: str | None = None,
) -> dict[str, Any]:
    exp_usd = as_required_int(elem, "expDlr")
    exp_wgt = as_required_int(elem, "expWgt")
    imp_usd = as_required_int(elem, "impDlr")
    imp_wgt = as_required_int(elem, "impWgt")
    balance = as_required_int(elem, "balPayments")
    if any(x < 0 for x in (exp_usd, exp_wgt, imp_usd, imp_wgt)):
        raise ValueError("negative amount/weight")
    if exp_usd - imp_usd != balance:
        raise ValueError("trade balance mismatch")
    return {
        "month": month,
        "country_code": country,
        "hs10": hs,
        "hs8": hs[:8],
        "hs6": hs[:6],
        "hs4": hs[:4],
        "hs2": hs[:2],
        "export_usd": exp_usd,
        "export_weight_kg": exp_wgt,
        "import_usd": imp_usd,
        "import_weight_kg": imp_wgt,
        "trade_balance_usd": balance,
        "hs_revision": hs_revision,
    }


def anomaly_row(
    elem: ET.Element,
    source: SourceManifest,
    month: str,
    hs: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "reason": reason,
        "month": month,
        "requested_country": source.country,
        "country_code_raw": pilot.safe_text(elem, "statCd"),
        "hs_code_raw": hs,
        "hs_length": len(hs),
        "name_ko": pilot.safe_text(elem, "statKor"),
        "export_usd": pilot.as_int(pilot.safe_text(elem, "expDlr")),
        "export_weight_kg": pilot.as_int(pilot.safe_text(elem, "expWgt")),
        "import_usd": pilot.as_int(pilot.safe_text(elem, "impDlr")),
        "import_weight_kg": pilot.as_int(pilot.safe_text(elem, "impWgt")),
        "trade_balance_usd": pilot.as_int(pilot.safe_text(elem, "balPayments")),
        "source_manifest": str(source.manifest_path),
        "source_raw_path": str(source.raw_path),
        "source_finished_at": source.finished_at,
    }


class MonthWriter:
    def __init__(self, staging_root: Path, year: str, month: str):
        # Keep the partition key distinct from the canonical `month=YYYYMM`
        # column. Using `month=01` here would collide with PyArrow's Hive
        # partition discovery and make the dataset awkward to read.
        self.partition_dir = staging_root / f"year={year}" / f"mm={month[4:]}"
        self.partition_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.partition_dir / "part-00000.parquet"
        self.writer = pq.ParquetWriter(
            self.path,
            SCHEMA,
            compression="zstd",
            compression_level=6,
            use_dictionary=True,
            write_statistics=True,
            version="2.6",
        )
        self.rows = 0

    def write(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        rows.sort(key=lambda r: (r["country_code"], r["hs10"]))
        table = pa.Table.from_pylist(rows, schema=SCHEMA)
        self.writer.write_table(table, row_group_size=min(len(rows), 100_000))
        self.rows += len(rows)

    def close(self) -> None:
        self.writer.close()


def normalize_sources(
    assignments: dict[str, dict[Path, tuple[SourceManifest, set[str]]]],
    staging_root: Path,
    hsk_revisions: dict[int, dict[str, str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    stats: Counter[str] = Counter()
    anomalies: list[dict[str, Any]] = []
    partition_rows: dict[str, int] = {}
    unknown_reference_codes: dict[tuple[int, str], dict[str, Any]] = {}
    summary_mismatch_details: list[dict[str, Any]] = []

    def get_writer(writers: dict[str, MonthWriter], year: str, month: str) -> MonthWriter:
        writer = writers.get(month)
        if writer is None:
            writer = MonthWriter(staging_root, year, month)
            writers[month] = writer
        return writer

    for year in sorted(assignments):
        writers: dict[str, MonthWriter] = {}
        buffers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        try:
            for _, (source, assigned_months) in sorted(
                assignments[year].items(), key=lambda kv: (kv[1][0].country, str(kv[0]))
            ):
                seen: set[tuple[str, str]] = set()
                full_source_selected = assigned_months == set(pilot.months_in_window(source.window))
                source_summary: dict[str, int] | None = None
                source_fact_totals = {measure: 0 for measure in MEASURES}
                source_fact_numeric_ok = True
                source_fact_rows = 0
                with gzip.open(source.raw_path, "rb") as fh:
                    for _, elem in ET.iterparse(fh, events=("end",)):
                        if pilot.strip_ns(elem.tag) != "item":
                            continue
                        stats["items_seen"] += 1
                        month = pilot.parse_year_month(pilot.safe_text(elem, "year"))
                        hs = pilot.safe_text(elem, "hsCd")
                        if month is None or hs in {"", "-"}:
                            if full_source_selected and hs in {"", "-"}:
                                candidate = measure_values(elem)
                                if candidate is not None:
                                    source_summary = candidate
                            stats["summary_or_nonfact_rows"] += 1
                            elem.clear()
                            continue
                        if month not in assigned_months:
                            stats["superseded_month_rows_skipped"] += 1
                            elem.clear()
                            continue
                        stats["assigned_fact_rows"] += 1
                        source_fact_rows += 1
                        raw_values = measure_values(elem)
                        if raw_values is None:
                            source_fact_numeric_ok = False
                        else:
                            for measure in MEASURES:
                                source_fact_totals[measure] += raw_values[measure]
                        stat_cd = pilot.safe_text(elem, "statCd")
                        if stat_cd and stat_cd != source.country:
                            anomalies.append(anomaly_row(elem, source, month, hs, "country_mismatch"))
                            stats["fatal_anomalies"] += 1
                            elem.clear()
                            continue
                        if not pilot.DIGITS10_RE.match(hs):
                            anomalies.append(anomaly_row(elem, source, month, hs, "non_hs10_code"))
                            stats["non_hs10_rows"] += 1
                            elem.clear()
                            continue
                        key = (month, hs)
                        if key in seen:
                            anomalies.append(anomaly_row(elem, source, month, hs, "duplicate_key"))
                            stats["fatal_anomalies"] += 1
                            elem.clear()
                            continue
                        seen.add(key)
                        try:
                            revision = None
                            if hsk_revisions is not None:
                                revision = hsk_revisions.get(int(month[:4]), {}).get(hs)
                                if revision is None:
                                    unknown = unknown_reference_codes.setdefault(
                                        (int(month[:4]), hs),
                                        {"fact_rows": 0, "months": set(), "name_ko_variants": set()},
                                    )
                                    unknown["fact_rows"] += 1
                                    unknown["months"].add(month)
                                    name_ko = pilot.safe_text(elem, "statKor")
                                    if name_ko:
                                        unknown["name_ko_variants"].add(name_ko)
                            row = canonical_row(elem, source.country, month, hs, revision)
                        except ValueError as exc:
                            anomalies.append(anomaly_row(elem, source, month, hs, str(exc)))
                            stats["fatal_anomalies"] += 1
                            elem.clear()
                            continue
                        buffers[month].append(row)
                        stats["canonical_rows"] += 1
                        if len(buffers[month]) >= 50_000:
                            writer = get_writer(writers, year, month)
                            writer.write(buffers[month])
                            buffers[month].clear()
                        elem.clear()

                if full_source_selected:
                    if source_summary is None:
                        stats["source_summary_missing"] += 1
                    elif not source_fact_numeric_ok:
                        stats["source_summary_unavailable_numeric"] += 1
                    else:
                        stats["source_summary_checked"] += 1
                        mismatch, accepted_rounding = classify_summary_differences(
                            source_fact_totals, source_summary, source_fact_rows
                        )
                        if mismatch:
                            stats["source_summary_mismatches"] += 1
                            summary_mismatch_details.append(
                                {
                                    "country_code": source.country,
                                    "window_start": source.window_start,
                                    "window_end": source.window_end,
                                    "source_manifest": str(source.manifest_path),
                                    "differences_fact_minus_summary": mismatch,
                                    "accepted_weight_rounding_fact_minus_summary": accepted_rounding,
                                    "fact_rows": source_fact_rows,
                                }
                            )
                        else:
                            stats["source_summary_matches"] += 1
                            if accepted_rounding:
                                stats["source_summary_weight_rounding_sources"] += 1
                                stats["source_summary_weight_rounding_fields"] += len(accepted_rounding)
                                stats["source_summary_weight_rounding_abs_kg"] += sum(
                                    abs(value) for value in accepted_rounding.values()
                                )

            for month, rows in sorted(buffers.items()):
                if rows:
                    writer = get_writer(writers, year, month)
                    writer.write(rows)
                    rows.clear()
        finally:
            for month, writer in writers.items():
                writer.close()
                partition_rows[month] = writer.rows
        print(
            f"normalized_year={year} canonical_rows_total={stats['canonical_rows']} "
            f"non_hs10_total={stats['non_hs10_rows']} fatal_total={stats['fatal_anomalies']}",
            flush=True,
        )

    stats_dict: dict[str, Any] = dict(stats)
    stats_dict["partition_rows"] = dict(sorted(partition_rows.items()))
    stats_dict["partition_count"] = len(partition_rows)
    stats_dict["hsk_reference_unknown_rows"] = sum(
        int(info["fact_rows"]) for info in unknown_reference_codes.values()
    )
    stats_dict["hsk_reference_unknown_unique"] = len(unknown_reference_codes)
    stats_dict["hsk_reference_unknown_codes"] = [
        {
            "reference_year": year,
            "hs10": hs10,
            "fact_rows": int(info["fact_rows"]),
            "months": ",".join(sorted(info["months"])),
            "name_ko_variants": " | ".join(sorted(info["name_ko_variants"])),
        }
        for (year, hs10), info in sorted(unknown_reference_codes.items())
    ]
    stats_dict["summary_mismatch_details"] = summary_mismatch_details
    stats_dict["stored_row_reconciliation"] = {
        "assigned_fact_rows": int(stats.get("assigned_fact_rows", 0)),
        "canonical_rows": int(stats.get("canonical_rows", 0)),
        "non_hs10_rows": int(stats.get("non_hs10_rows", 0)),
        "fatal_anomalies": int(stats.get("fatal_anomalies", 0)),
        "reconciles": int(stats.get("assigned_fact_rows", 0))
        == int(stats.get("canonical_rows", 0))
        + int(stats.get("non_hs10_rows", 0))
        + int(stats.get("fatal_anomalies", 0)),
    }
    return stats_dict, anomalies


def write_unknown_reference_audit(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["reference_year", "hs10", "fact_rows", "months", "name_ko_variants"],
        )
        w.writeheader()
        w.writerows(rows)


def write_anomaly_audit(base: Path, anomalies: list[dict[str, Any]]) -> tuple[Path, Path]:
    base.mkdir(parents=True, exist_ok=True)
    csv_path = base / "normalization_anomalies.csv"
    parquet_path = base / "normalization_anomalies.parquet"
    fields = [
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
        "source_manifest",
        "source_raw_path",
        "source_finished_at",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in anomalies:
            w.writerow(row)
    pq.write_table(pa.Table.from_pylist(anomalies, schema=ANOMALY_SCHEMA), parquet_path, compression="zstd")
    return csv_path, parquet_path


def verify_parquet_dataset(root: Path) -> dict[str, Any]:
    files = sorted(root.glob("year=*/mm=*/part-*.parquet"))
    total_rows = 0
    total_bytes = 0
    schema_ok = True
    month_mismatches = 0
    duplicate_keys = 0
    for path in files:
        pf = pq.ParquetFile(path)
        total_rows += pf.metadata.num_rows
        total_bytes += path.stat().st_size
        if not pf.schema_arrow.equals(SCHEMA, check_metadata=False):
            schema_ok = False
        table = pf.read(columns=["month", "country_code", "hs10"])
        expected_month = path.parent.name.split("=", 1)[1]
        expected_year = path.parent.parent.name.split("=", 1)[1]
        full_month = expected_year + expected_month
        values = table.column("month").to_pylist()
        month_mismatches += sum(v != full_month for v in values)
        # Each file is one month. Checking a set here is bounded by a single-month dataset.
        keys = list(zip(table.column("country_code").to_pylist(), table.column("hs10").to_pylist()))
        duplicate_keys += len(keys) - len(set(keys))
    return {
        "parquet_files": len(files),
        "parquet_rows": total_rows,
        "parquet_bytes": total_bytes,
        "schema_ok": schema_ok,
        "partition_month_mismatches": month_mismatches,
        "duplicate_keys": duplicate_keys,
    }


def safe_replace_dir(staging: Path, target: Path, overwrite: bool) -> None:
    target_parent = target.parent.resolve()
    if staging.resolve().parent != target_parent:
        raise RuntimeError("staging and target must share a parent directory")
    backup = target.with_name(target.name + ".previous")
    if target.exists() and not overwrite:
        raise RuntimeError(f"output exists; pass --overwrite to rebuild: {target}")
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        target.rename(backup)
    try:
        staging.rename(target)
    except Exception:
        if backup.exists() and not target.exists():
            backup.rename(target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Normalize selected KCS raw XML to strict HSK10 Parquet")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--country-reference", default="data/reference/country_reference.csv")
    p.add_argument("--hsk-reference", default="data/reference/hsk_code_reference.parquet")
    p.add_argument("--output", default="data/normalized/hs10")
    p.add_argument("--start-month", default=None)
    p.add_argument("--end-month", default=None)
    p.add_argument("--require-full-coverage", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    t0 = time.monotonic()
    data_dir = Path(args.data_dir).resolve()
    country_ref = Path(args.country_reference).resolve()
    hsk_ref = Path(args.hsk_reference).resolve()
    target = Path(args.output).resolve()
    official_codes = load_country_reference(country_ref)
    hsk_revisions = load_hsk_revision_map(hsk_ref)
    sources, missing_raw = discover_successful_sources(data_dir, official_codes)
    if missing_raw:
        raise SystemExit(f"successful manifests with missing raw files: {len(missing_raw)}")
    selected, candidate_counts = select_sources_by_country_month(sources, args.start_month, args.end_month)
    if not selected:
        raise SystemExit("no selected country-month sources")

    months = sorted({m for _, m in selected})
    print(f"successful_source_manifests={len(sources)}")
    print(f"selected_country_months={len(selected)}")
    print(f"selected_month_range={months[0]}-{months[-1]}")
    print(f"overlap_country_months={sum(n > 1 for n in candidate_counts.values())}")

    if args.require_full_coverage:
        start = args.start_month or months[0]
        end = args.end_month or months[-1]
        expected_months = pilot.months_in_window(pilot.Window(start, end))
        expected = {(c, m) for c in official_codes for m in expected_months}
        missing = sorted(expected - set(selected))
        if missing:
            example = ",".join(f"{c}:{m}" for c, m in missing[:10])
            raise SystemExit(f"full coverage missing {len(missing)} country-months; examples={example}")
        print(f"full_coverage_ok={len(expected)}")

    audit_dir = data_dir / "audits" / "normalization"
    selection_path = audit_dir / "source_selection.csv"
    write_source_selection_audit(selection_path, selected, candidate_counts)
    if args.dry_run:
        print(f"source_selection={selection_path}")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not args.overwrite:
        raise SystemExit(f"output exists; pass --overwrite to rebuild: {target}")
    staging = target.with_name(target.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    assignments = selected_assignments(selected)
    stats, anomalies = normalize_sources(assignments, staging, hsk_revisions)
    anomaly_csv, anomaly_parquet = write_anomaly_audit(audit_dir, anomalies)
    unknown_reference_csv = audit_dir / "hsk_reference_unknown_codes.csv"
    write_unknown_reference_audit(unknown_reference_csv, stats["hsk_reference_unknown_codes"])
    verify = verify_parquet_dataset(staging)
    fatal = int(stats.get("fatal_anomalies", 0))
    canonical_rows = int(stats.get("canonical_rows", 0))
    if verify["parquet_rows"] != canonical_rows:
        fatal += 1
    if not verify["schema_ok"] or verify["partition_month_mismatches"] or verify["duplicate_keys"]:
        fatal += 1
    if int(stats.get("source_summary_mismatches", 0)):
        fatal += 1
    if not bool((stats.get("stored_row_reconciliation") or {}).get("reconciles")):
        fatal += 1

    manifest = {
        "generated_at": utc_now(),
        "data_dir": str(data_dir),
        "country_reference": str(country_ref),
        "hsk_reference": str(hsk_ref),
        "output": str(target),
        "start_month": args.start_month,
        "end_month": args.end_month,
        "successful_source_manifests": len(sources),
        "selected_country_months": len(selected),
        "selected_unique_raw_sources": len({s.raw_path for s in selected.values()}),
        "overlap_country_months": sum(n > 1 for n in candidate_counts.values()),
        "normalization_stats": stats,
        "verification": verify,
        "anomaly_rows": len(anomalies),
        "non_hs10_anomaly_rows": sum(a["reason"] == "non_hs10_code" for a in anomalies),
        "fatal_anomalies": int(stats.get("fatal_anomalies", 0)),
        "source_selection_csv": str(selection_path),
        "anomaly_csv": str(anomaly_csv),
        "anomaly_parquet": str(anomaly_parquet),
        "hsk_reference_unknown_csv": str(unknown_reference_csv),
        "hsk_reference_unknown_rows": stats["hsk_reference_unknown_rows"],
        "hsk_reference_unknown_unique": stats["hsk_reference_unknown_unique"],
        "source_summary_checked": int(stats.get("source_summary_checked", 0)),
        "source_summary_matches": int(stats.get("source_summary_matches", 0)),
        "source_summary_mismatches": int(stats.get("source_summary_mismatches", 0)),
        "source_summary_missing": int(stats.get("source_summary_missing", 0)),
        "source_summary_weight_rounding_sources": int(
            stats.get("source_summary_weight_rounding_sources", 0)
        ),
        "source_summary_weight_rounding_abs_kg": int(
            stats.get("source_summary_weight_rounding_abs_kg", 0)
        ),
        "stored_row_reconciliation": stats.get("stored_row_reconciliation"),
        "elapsed_seconds": round(time.monotonic() - t0, 3),
        "hs_revision_policy": (
            "Use the official annual KCS CLIP HSK edition only when (reference_year, hs10) is present; "
            "otherwise keep hs_revision null and audit the code without dropping the trade fact."
        ),
    }
    audit_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = audit_dir / "normalization_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if fatal:
        print(f"normalization_failed fatal_checks={fatal}; staging_preserved={staging}", file=sys.stderr)
        print(f"normalization_manifest={manifest_path}")
        return 2

    safe_replace_dir(staging, target, args.overwrite)
    print(f"canonical_rows={canonical_rows}")
    print(f"non_hs10_anomalies={manifest['non_hs10_anomaly_rows']}")
    print(f"parquet_files={verify['parquet_files']}")
    print(f"parquet_bytes={verify['parquet_bytes']}")
    print(f"output={target}")
    print(f"normalization_manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
