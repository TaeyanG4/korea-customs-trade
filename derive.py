#!/usr/bin/env python3
"""Derive HS6/HS4/HS2 monthly country aggregates from strict HSK10 Parquet."""
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def schema_for_level(level: int) -> pa.Schema:
    if level == 6:
        keys = [
            pa.field("month", pa.string(), nullable=False),
            pa.field("country_code", pa.string(), nullable=False),
            pa.field("hs6", pa.string(), nullable=False),
            pa.field("hs4", pa.string(), nullable=False),
            pa.field("hs2", pa.string(), nullable=False),
        ]
    elif level == 4:
        keys = [
            pa.field("month", pa.string(), nullable=False),
            pa.field("country_code", pa.string(), nullable=False),
            pa.field("hs4", pa.string(), nullable=False),
            pa.field("hs2", pa.string(), nullable=False),
        ]
    elif level == 2:
        keys = [
            pa.field("month", pa.string(), nullable=False),
            pa.field("country_code", pa.string(), nullable=False),
            pa.field("hs2", pa.string(), nullable=False),
        ]
    else:
        raise ValueError(f"unsupported HS level: {level}")
    return pa.schema(
        keys + [pa.field(m, pa.int64(), nullable=False) for m in MEASURES],
        metadata={
            b"dataset": f"South Korea Customs Trade - derived HS{level} facts".encode(),
            b"derivation": b"aggregated locally from strict HSK10 Parquet; no HS2/4/6 API query",
        },
    )


def aggregate_table(table: pa.Table, level: int) -> pa.Table:
    code_col = f"hs{level}"
    group_keys = ["month", "country_code", code_col]
    selected = table.select(group_keys + MEASURES)
    grouped = selected.group_by(group_keys).aggregate([(m, "sum") for m in MEASURES])
    rename = {
        f"{m}_sum": m for m in MEASURES
    }
    grouped = grouped.rename_columns([rename.get(n, n) for n in grouped.column_names])

    rows = grouped.to_pylist()
    if level == 6:
        for row in rows:
            row["hs4"] = row["hs6"][:4]
            row["hs2"] = row["hs6"][:2]
        sort_keys = [("country_code", "ascending"), ("hs6", "ascending")]
    elif level == 4:
        for row in rows:
            row["hs2"] = row["hs4"][:2]
        sort_keys = [("country_code", "ascending"), ("hs4", "ascending")]
    else:
        sort_keys = [("country_code", "ascending"), ("hs2", "ascending")]
    out = pa.Table.from_pylist(rows, schema=schema_for_level(level))
    return out.sort_by(sort_keys)


def measure_totals_arrow(table: pa.Table) -> dict[str, int]:
    # Avoid importing pandas for production aggregation.
    import pyarrow.compute as pc

    totals = {}
    for measure in MEASURES:
        scalar = pc.sum(table[measure])
        totals[measure] = int(scalar.as_py() or 0)
    return totals


def derive_all(
    hs10_root: Path,
    staging_root: Path,
    levels: list[int],
) -> dict[str, Any]:
    files = sorted(hs10_root.glob("year=*/mm=*/part-*.parquet"))
    if not files:
        raise RuntimeError(f"no HSK10 parquet files found under {hs10_root}")

    stats: dict[str, Any] = {
        "input_files": len(files),
        "input_rows": 0,
        "input_bytes": sum(p.stat().st_size for p in files),
        "levels": {str(level): {"rows": 0, "bytes": 0, "files": 0} for level in levels},
        "totals": {"hs10": {m: 0 for m in MEASURES}},
    }
    for level in levels:
        stats["totals"][f"hs{level}"] = {m: 0 for m in MEASURES}

    year_counts: dict[str, int] = defaultdict(int)
    for i, path in enumerate(files, 1):
        table = pq.ParquetFile(path).read()
        stats["input_rows"] += table.num_rows
        input_totals = measure_totals_arrow(table)
        for m in MEASURES:
            stats["totals"]["hs10"][m] += input_totals[m]

        year = path.parent.parent.name.split("=", 1)[1]
        mm = path.parent.name.split("=", 1)[1]
        expected_month = year + mm
        if any(v != expected_month for v in table["month"].to_pylist()):
            raise RuntimeError(f"month/partition mismatch in {path}")

        for level in levels:
            aggregated = aggregate_table(table, level)
            totals = measure_totals_arrow(aggregated)
            if totals != input_totals:
                raise RuntimeError(
                    f"HS{level} aggregate total mismatch for {expected_month}: {totals} != {input_totals}"
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
            stats["levels"][str(level)]["rows"] += aggregated.num_rows
            stats["levels"][str(level)]["bytes"] += out.stat().st_size
            stats["levels"][str(level)]["files"] += 1
            for m in MEASURES:
                stats["totals"][f"hs{level}"][m] += totals[m]
        year_counts[year] += 1
        if i == len(files) or (i < len(files) and files[i].parent.parent.name != path.parent.parent.name):
            print(
                f"derived_year={year} monthly_partitions={year_counts[year]} "
                + " ".join(f"hs{l}_rows={stats['levels'][str(l)]['rows']}" for l in levels),
                flush=True,
            )

    for level in levels:
        if stats["totals"][f"hs{level}"] != stats["totals"]["hs10"]:
            raise RuntimeError(f"global HS{level} totals do not match HSK10")
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
    ap = argparse.ArgumentParser(description="Derive HS6/HS4/HS2 Parquet from HSK10")
    ap.add_argument("--input", default="data/normalized/hs10")
    ap.add_argument("--output", default="data/derived")
    ap.add_argument("--levels", nargs="+", type=int, default=[6, 4, 2])
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    levels = list(dict.fromkeys(args.levels))
    if any(level not in {2, 4, 6} for level in levels):
        raise SystemExit("--levels supports only 2 4 6")

    t0 = time.monotonic()
    hs10_root = Path(args.input).resolve()
    target = Path(args.output).resolve()
    staging = target.with_name(target.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        stats = derive_all(hs10_root, staging, levels)
    except Exception:
        # Preserve staging output for debugging; the previously committed derived
        # dataset remains untouched until all totals reconcile.
        raise

    safe_replace_derived(staging, target, args.overwrite)
    manifest = {
        "generated_at": utc_now(),
        "input": str(hs10_root),
        "output": str(target),
        "levels": levels,
        "stats": stats,
        "elapsed_seconds": round(time.monotonic() - t0, 3),
        "derivation_policy": "HS6/HS4/HS2 are aggregated locally from strict HSK10 only; no lower-level KCS API queries",
    }
    audit_dir = target.parent / "audits" / "derivation"
    # The default target is data/derived, so keep audits under data/audits.
    if target.name == "derived":
        audit_dir = target.parent / "audits" / "derivation"
    audit_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = audit_dir / "derivation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"input_rows={stats['input_rows']}")
    for level in levels:
        s = stats["levels"][str(level)]
        print(f"hs{level}_rows={s['rows']} hs{level}_bytes={s['bytes']} files={s['files']}")
    print(f"derivation_manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
