import gzip
import json
from pathlib import Path

import pyarrow.dataset as ds
import pyarrow.parquet as pq

import normalize
import pilot


def _xml(country: str, month: str, rows: list[tuple[str, int, int]]) -> bytes:
    items = [
        "<item><year>total</year><statCd>-</statCd><hsCd>-</hsCd><statKor>-</statKor>"
        "<expDlr>0</expDlr><expWgt>0</expWgt><impDlr>0</impDlr><impWgt>0</impWgt>"
        "<balPayments>0</balPayments></item>"
    ]
    ym = f"{month[:4]}.{month[4:]}"
    for hs, exp, imp in rows:
        items.append(
            f"<item><year>{ym}</year><statCd>{country}</statCd><hsCd>{hs}</hsCd><statKor>name</statKor>"
            f"<expDlr>{exp}</expDlr><expWgt>1</expWgt><impDlr>{imp}</impDlr><impWgt>1</impWgt>"
            f"<balPayments>{exp-imp}</balPayments></item>"
        )
    return ("<?xml version='1.0' encoding='UTF-8'?><response><header><resultCode>00</resultCode>"
            "</header><body><items>" + "".join(items) + "</items></body></response>").encode()


def _write_source(
    data_dir: Path,
    country: str,
    start: str,
    end: str,
    finished_at: str,
    xml: bytes,
) -> Path:
    year = start[:4]
    raw_dir = data_dir / "raw" / f"year={year}" / f"country={country}"
    man_dir = data_dir / "audits" / "manifests" / f"year={year}" / f"country={country}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    man_dir.mkdir(parents=True, exist_ok=True)
    raw = raw_dir / f"response_{start}-{end}.xml.gz"
    with gzip.open(raw, "wb") as f:
        f.write(xml)
    manifest = man_dir / f"request_{start}-{end}.json"
    manifest.write_text(
        json.dumps(
            {
                "country": country,
                "window_start": start,
                "window_end": end,
                "success": True,
                "status": "success",
                "requested_at": finished_at,
                "finished_at": finished_at,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_latest_overlapping_source_wins(tmp_path: Path):
    old = _write_source(tmp_path, "US", "202501", "202512", "2026-01-01T00:00:00+00:00", _xml("US", "202501", [("0101219000", 10, 0)]))
    new = _write_source(tmp_path, "US", "202501", "202503", "2026-02-01T00:00:00+00:00", _xml("US", "202501", [("0101219000", 20, 0)]))
    sources, missing = normalize.discover_successful_sources(tmp_path, {"US"})
    assert not missing
    selected, counts = normalize.select_sources_by_country_month(sources)
    assert selected[("US", "202501")].manifest_path == new
    assert counts[("US", "202501")] == 2
    assert selected[("US", "202504")].manifest_path == old


def test_strict_hs10_normalization_quarantines_short_code(tmp_path: Path):
    manifest = _write_source(
        tmp_path,
        "US",
        "202501",
        "202501",
        "2026-01-01T00:00:00+00:00",
        _xml("US", "202501", [("0101219000", 10, 0), ("761699", 2, 0)]),
    )
    sources, _ = normalize.discover_successful_sources(tmp_path, {"US"})
    selected, _ = normalize.select_sources_by_country_month(sources)
    staging = tmp_path / "normalized"
    stats, anomalies = normalize.normalize_sources(normalize.selected_assignments(selected), staging)
    assert stats["canonical_rows"] == 1
    assert stats["non_hs10_rows"] == 1
    assert stats.get("fatal_anomalies", 0) == 0
    assert anomalies[0]["hs_code_raw"] == "761699"
    file = staging / "year=2025" / "mm=01" / "part-00000.parquet"
    table = pq.ParquetFile(file).read()
    assert table.num_rows == 1
    row = table.to_pylist()[0]
    assert row["hs10"] == "0101219000"
    assert row["hs6"] == "010121"
    assert row["hs4"] == "0101"
    assert row["hs2"] == "01"
    assert row["hs_revision"] is None
    assert row["export_usd"] == 10


def test_source_priority_prefers_narrower_window_when_timestamp_ties(tmp_path: Path):
    a = normalize.SourceManifest(tmp_path / "a", tmp_path / "ra", "US", "202501", "202512", "", "", 1.0)
    b = normalize.SourceManifest(tmp_path / "b", tmp_path / "rb", "US", "202501", "202503", "", "", 1.0)
    selected, _ = normalize.select_sources_by_country_month([a, b])
    assert selected[("US", "202501")] == b


def test_multiple_sources_append_to_same_month_parquet(tmp_path: Path):
    _write_source(
        tmp_path,
        "US",
        "202501",
        "202501",
        "2026-01-01T00:00:00+00:00",
        _xml("US", "202501", [("0101219000", 10, 0)]),
    )
    _write_source(
        tmp_path,
        "CN",
        "202501",
        "202501",
        "2026-01-01T00:00:00+00:00",
        _xml("CN", "202501", [("0201100000", 20, 1)]),
    )
    sources, missing = normalize.discover_successful_sources(tmp_path, {"US", "CN"})
    assert not missing
    selected, _ = normalize.select_sources_by_country_month(sources)
    staging = tmp_path / "normalized"
    stats, anomalies = normalize.normalize_sources(normalize.selected_assignments(selected), staging)
    assert stats["canonical_rows"] == 2
    assert not anomalies
    file = staging / "year=2025" / "mm=01" / "part-00000.parquet"
    table = pq.ParquetFile(file).read()
    assert table.num_rows == 2
    assert {row["country_code"] for row in table.to_pylist()} == {"US", "CN"}
    dataset = ds.dataset(staging, format="parquet", partitioning="hive")
    assert dataset.count_rows() == 2
    assert "month" in dataset.schema.names
    assert "year" in dataset.schema.names
    assert "mm" in dataset.schema.names
