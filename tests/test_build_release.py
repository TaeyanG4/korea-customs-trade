from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import build_release


def _write_month(root: Path, year: str, mm: str, rows: list[dict]) -> None:
    out = root / f"year={year}" / f"mm={mm}"
    out.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            pa.field("month", pa.string(), nullable=False),
            pa.field("country_code", pa.string(), nullable=False),
            pa.field("hs10", pa.string(), nullable=False),
            pa.field("value", pa.int64(), nullable=False),
        ]
    )
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), out / "part-00000.parquet")


def test_consolidate_parquet_streams_all_partitions(tmp_path: Path):
    root = tmp_path / "input"
    _write_month(
        root,
        "2025",
        "01",
        [{"month": "202501", "country_code": "US", "hs10": "0101219000", "value": 1}],
    )
    _write_month(
        root,
        "2025",
        "02",
        [{"month": "202502", "country_code": "US", "hs10": "0101219000", "value": 2}],
    )
    output = tmp_path / "combined.parquet"
    info = build_release.consolidate_parquet(root, output)
    assert info["rows"] == 2
    assert info["source_files"] == 2
    assert len(info["sha256"]) == 64
    table = pq.read_table(output)
    assert table["month"].to_pylist() == ["202501", "202502"]
    assert table["value"].to_pylist() == [1, 2]


def test_release_anomaly_table_filters_and_renames(tmp_path: Path):
    schema = pa.schema(
        [
            pa.field("reason", pa.string(), nullable=False),
            pa.field("month", pa.string(), nullable=False),
            pa.field("requested_country", pa.string(), nullable=False),
            pa.field("country_code_raw", pa.string()),
            pa.field("hs_code_raw", pa.string()),
            pa.field("hs_length", pa.int64(), nullable=False),
            pa.field("name_ko", pa.string()),
            pa.field("export_usd", pa.int64()),
            pa.field("export_weight_kg", pa.int64()),
            pa.field("import_usd", pa.int64()),
            pa.field("import_weight_kg", pa.int64()),
            pa.field("trade_balance_usd", pa.int64()),
            pa.field("source_manifest", pa.string(), nullable=False),
            pa.field("source_raw_path", pa.string(), nullable=False),
            pa.field("source_finished_at", pa.string()),
        ]
    )
    rows = [
        {
            "reason": "non_hs10_code",
            "month": "201702",
            "requested_country": "US",
            "country_code_raw": "US",
            "hs_code_raw": "761699",
            "hs_length": 6,
            "name_ko": "기타",
            "export_usd": 172,
            "export_weight_kg": 1,
            "import_usd": 0,
            "import_weight_kg": 0,
            "trade_balance_usd": 172,
            "source_manifest": "internal.json",
            "source_raw_path": "internal.xml.gz",
            "source_finished_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "reason": "negative_weight",
            "month": "201606",
            "requested_country": "US",
            "country_code_raw": "US",
            "hs_code_raw": "1212212090",
            "hs_length": 10,
            "name_ko": "기타",
            "export_usd": 0,
            "export_weight_kg": 0,
            "import_usd": 44,
            "import_weight_kg": -23,
            "trade_balance_usd": -44,
            "source_manifest": "internal.json",
            "source_raw_path": "internal.xml.gz",
            "source_finished_at": "2026-01-01T00:00:00+00:00",
        },
    ]
    source = tmp_path / "anomalies.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), source)
    filtered = build_release.release_anomaly_table(source, "non_hs10_code")
    assert filtered.num_rows == 1
    assert "requested_country" not in filtered.column_names
    assert "country_code" in filtered.column_names
    assert "source_manifest" not in filtered.column_names
    assert filtered["raw_hs_code"].to_pylist() == ["761699"]
