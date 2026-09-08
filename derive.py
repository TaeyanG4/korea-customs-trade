#!/usr/bin/env python3
"""Derive analyst-ready HS8/HS6/HS4/HS2 monthly aggregates.

The strict HSK10 fact table remains the canonical grain. Rare upstream rows
with shorter numeric HS codes are never padded into HSK10. Instead, they are
added only to hierarchy levels that can be identified safely from the source
prefix (for example, a 6-digit source row can contribute to HS6/HS4/HS2 but
not HS8).
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

import normalize


MEASURES = [
    "export_usd",
    "export_weight_kg",
    "import_usd",
    "import_weight_kg",
    "trade_balance_usd",
]
RESIDUAL_FIELDS = [f"residual_{m}" for m in MEASURES]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def level_key_fields(level: int) -> list[str]:
    if level == 8:
        return ["month", "country_code", "hs8", "hs6", "hs4", "hs2"]
    if level == 6:
        return ["month", "country_code", "hs6", "hs4", "hs2"]
    if level == 4:
        return ["month", "country_code", "hs4", "hs2"]
    if level == 2:
        return ["month", "country_code", "hs2"]
    raise ValueError(f"unsupported HS level: {level}")


def schema_for_level(level: int) -> pa.Schema:
    fields = [pa.field(name, pa.string(), nullable=False) for name in level_key_fields(level)]
    fields += [pa.field(m, pa.int64(), nullable=False) for m in MEASURES]
    fields += [pa.field(m, pa.int64(), nullable=False) for m in RESIDUAL_FIELDS]
    fields += [
        pa.field("source_row_count", pa.int64(), nullable=False),
        pa.field("exception_row_count", pa.int64(), nullable=False),
        pa.field("has_residual", pa.bool_(), nullable=False),
    ]
    return pa.schema(
        fields,
        metadata={
            b"dataset": f"South Korea Customs Trade - derived HS{level} facts".encode(),
            b"derivation": (
                b"aggregated locally from strict HSK10; shorter numeric source residuals are included "
                b"only where their prefix maps safely to this level"
            ),
        },
    )


def code_hierarchy(code: str, level: int) -> dict[str, str]:
    out = {f"hs{level}": code[:level]}
    if level >= 8:
        out["hs6"] = code[:6]
        out["hs4"] = code[:4]
        out["hs2"] = code[:2]
    elif level >= 6:
        out["hs4"] = code[:4]
        out["hs2"] = code[:2]
    elif level >= 4:
        out["hs2"] = code[:2]
    return out


def aggregate_table(
    table: pa.Table,
    level: int,
    residual_rows: list[dict[str, Any]] | None = None,
) -> pa.Table:
    """Aggregate one monthly HSK10 table and add safely mappable residuals."""
    code_col = f"hs{level}"
    group_keys = ["month", "country_code", code_col]
    selected = table.select(group_keys + ["hs10"] + MEASURES)
    aggregations = [(m, "sum") for m in MEASURES] + [("hs10", "count")]
    grouped = selected.group_by(group_keys).aggregate(aggregations)
    rename = {f"{m}_sum": m for m in MEASURES}
    rename["hs10_count"] = "source_row_count"
    grouped = grouped.rename_columns([rename.get(n, n) for n in grouped.column_names])

    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in grouped.to_pylist():
        code = str(row[code_col])
        row.update(code_hierarchy(code, level))
        for measure in MEASURES:
            row[f"residual_{measure}"] = 0
        row["exception_row_count"] = 0
        row["has_residual"] = False
        key = (str(row["month"]), str(row["country_code"]), code)
        rows_by_key[key] = row

    for residual in residual_rows or []:
        code = str(residual.get("hs_code_raw") or "").strip()
        if not code.isdigit() or not (level <= len(code) < 10):
            continue
        month = str(residual.get("month") or "")
        country = str(residual.get("requested_country") or "")
        mapped = code[:level]
        key = (month, country, mapped)
        row = rows_by_key.get(key)
        if row is None:
            row = {
                "month": month,
                "country_code": country,
                **code_hierarchy(mapped, level),
                **{m: 0 for m in MEASURES},
                **{f"residual_{m}": 0 for m in MEASURES},
                "source_row_count": 0,
                "exception_row_count": 0,
                "has_residual": False,
            }
            rows_by_key[key] = row
        for measure in MEASURES:
            value = residual.get(measure)
            if value is None:
                raise RuntimeError(f"residual row has missing {measure}: {residual}")
            value = int(value)
            row[measure] += value
            row[f"residual_{measure}"] += value
        row["source_row_count"] += 1
        row["exception_row_count"] += 1
        row["has_residual"] = True

    rows = list(rows_by_key.values())
    sort_keys = [("country_code", "ascending"), (code_col, "ascending")]
    out = pa.Table.from_pylist(rows, schema=schema_for_level(level))
    return out.sort_by(sort_keys)


def measure_totals_arrow(table: pa.Table) -> dict[str, int]:
    import pyarrow.compute as pc

    totals: dict[str, int] = {}
    for measure in MEASURES:
        scalar = pc.sum(table[measure])
        totals[measure] = int(scalar.as_py() or 0)
    return totals


def residual_measure_totals(rows: list[dict[str, Any]], level: int) -> tuple[dict[str, int], int]:
    totals = {m: 0 for m in MEASURES}
    mapped_rows = 0
    for row in rows:
        code = str(row.get("hs_code_raw") or "").strip()
        if not code.isdigit() or not (level <= len(code) < 10):
            continue
        mapped_rows += 1
        for measure in MEASURES:
            value = row.get(measure)
            if value is None:
                raise RuntimeError(f"residual row has missing {measure}: {row}")
            totals[measure] += int(value)
    return totals, mapped_rows


def load_residual_rows(path: Path) -> dict[str, list[dict[str, Any]]]:
    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not path.exists():
        return {}
    table = pq.ParquetFile(path).read()
    for row in table.to_pylist():
        if row.get("reason") != "non_hs10_code":
            continue
        by_month[str(row["month"])].append(row)
    return dict(by_month)


def derive_all(
    hs10_root: Path,
    staging_root: Path,
    levels: list[int],
    residuals_by_month: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    files = sorted(hs10_root.glob("year=*/mm=*/part-*.parquet"))
    if not files:
        raise RuntimeError(f"no HSK10 parquet files found under {hs10_root}")

    residuals_by_month = residuals_by_month or {}
    stats: dict[str, Any] = {
        "input_files": len(files),
        "input_rows": 0,
        "input_bytes": sum(p.stat().st_size for p in files),
        "residual_input_rows": sum(len(v) for v in residuals_by_month.values()),
        "levels": {
            str(level): {"rows": 0, "bytes": 0, "files": 0, "mapped_residual_rows": 0}
            for level in levels
        },
        "totals": {"hs10": {m: 0 for m in MEASURES}},
        "residual_totals": {str(level): {m: 0 for m in MEASURES} for level in levels},
    }
    for level in levels:
        stats["totals"][f"hs{level}"] = {m: 0 for m in MEASURES}

    year_counts: dict[str, int] = defaultdict(int)
    for i, path in enumerate(files, 1):
        table = pq.ParquetFile(path).read()
        stats["input_rows"] += table.num_rows
        input_totals = measure_totals_arrow(table)
        for measure in MEASURES:
            stats["totals"]["hs10"][measure] += input_totals[measure]

        year = path.parent.parent.name.split("=", 1)[1]
        mm = path.parent.name.split("=", 1)[1]
        expected_month = year + mm
        if any(v != expected_month for v in table["month"].to_pylist()):
            raise RuntimeError(f"month/partition mismatch in {path}")
        month_residuals = residuals_by_month.get(expected_month, [])

        for level in levels:
            residual_totals, mapped_rows = residual_measure_totals(month_residuals, level)
            aggregated = aggregate_table(table, level, month_residuals)
            totals = measure_totals_arrow(aggregated)
            expected_totals = {
                measure: input_totals[measure] + residual_totals[measure]
                for measure in MEASURES
            }
            if totals != expected_totals:
                raise RuntimeError(
                    f"HS{level} aggregate total mismatch for {expected_month}: {totals} != {expected_totals}"
                )
            out_dir = staging_root / f"hs{level}" / f"year={year}" / f"mm={mm}"
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / "part-00000.parquet"
            pq.write_table(
                aggregated,
                out,
                compression="zstd",
                compression_level=6,
                use_dictionary=True,
                write_statistics=True,
                version="2.6",
                row_group_size=min(max(aggregated.num_rows, 1), 100_000),
            )
            level_stats = stats["levels"][str(level)]
            level_stats["rows"] += aggregated.num_rows
            level_stats["bytes"] += out.stat().st_size
            level_stats["files"] += 1
            level_stats["mapped_residual_rows"] += mapped_rows
            for measure in MEASURES:
                stats["totals"][f"hs{level}"][measure] += totals[measure]
                stats["residual_totals"][str(level)][measure] += residual_totals[measure]
        year_counts[year] += 1
        if i == len(files) or (i < len(files) and files[i].parent.parent.name != path.parent.parent.name):
            print(
                f"derived_year={year} monthly_partitions={year_counts[year]} "
                + " ".join(f"hs{level}_rows={stats['levels'][str(level)]['rows']}" for level in levels),
                flush=True,
            )

    for level in levels:
        expected_global = {
            measure: stats["totals"]["hs10"][measure] + stats["residual_totals"][str(level)][measure]
            for measure in MEASURES
        }
        if stats["totals"][f"hs{level}"] != expected_global:
            raise RuntimeError(f"global HS{level} totals do not reconcile to HSK10 + mapped residuals")
    return stats


def safe_replace_derived(staging: Path, target: Path, overwrite: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_name(target.name + ".previous")
    if target.exists() and not overwrite:
        raise RuntimeError(f"derived output exists; pass --overwrite: {target}")
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Derive HS8/HS6/HS4/HS2 Parquet from strict HSK10")
    ap.add_argument("--input", default="data/normalized/hs10")
    ap.add_argument("--exceptions", default="data/audits/normalization/normalization_anomalies.parquet")
    ap.add_argument("--output", default="data/derived")
    ap.add_argument("--levels", nargs="+", type=int, default=[8, 6, 4, 2])
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    levels = list(dict.fromkeys(args.levels))
    if any(level not in {2, 4, 6, 8} for level in levels):
        raise SystemExit("--levels supports only 2 4 6 8")

    t0 = time.monotonic()
    hs10_root = Path(args.input).resolve()
    exception_path = Path(args.exceptions).resolve()
    target = Path(args.output).resolve()
    staging = target.with_name(target.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    residuals_by_month = load_residual_rows(exception_path)
    stats = derive_all(hs10_root, staging, levels, residuals_by_month)

    safe_replace_derived(staging, target, args.overwrite)
    manifest = {
        "generated_at": utc_now(),
        "input": str(hs10_root),
        "exceptions": str(exception_path),
        "output": str(target),
        "levels": levels,
        "stats": stats,
        "elapsed_seconds": round(time.monotonic() - t0, 3),
        "derivation_policy": (
            "HS8/HS6/HS4/HS2 are aggregated locally from strict HSK10. Numeric non-HSK10 source residuals "
            "are included only at levels identifiable from their existing prefix; no zero-padding or allocation is inferred."
        ),
    }
    audit_dir = target.parent / "audits" / "derivation"
    audit_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = audit_dir / "derivation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"input_rows={stats['input_rows']}")
    print(f"residual_input_rows={stats['residual_input_rows']}")
    for level in levels:
        info = stats["levels"][str(level)]
        print(
            f"hs{level}_rows={info['rows']} hs{level}_bytes={info['bytes']} "
            f"files={info['files']} mapped_residual_rows={info['mapped_residual_rows']}"
        )
    print(f"derivation_manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
