import gzip
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pyarrow.dataset as ds
import pyarrow.parquet as pq

import normalize
import pilot


def _xml(country: str, month: str, rows: list[tuple[str, int, int]]) -> bytes:
    exp_total = sum(exp for _, exp, _ in rows)
    imp_total = sum(imp for _, _, imp in rows)
    weight_total = len(rows)
    items = [
        "<item><year>total</year><statCd>-</statCd><hsCd>-</hsCd><statKor>-</statKor>"
        f"<expDlr>{exp_total}</expDlr><expWgt>{weight_total}</expWgt>"
        f"<impDlr>{imp_total}</impDlr><impWgt>{weight_total}</impWgt>"
        f"<balPayments>{exp_total-imp_total}</balPayments></item>"
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
    assert stats["source_summary_matches"] == 1
    assert stats.get("source_summary_mismatches", 0) == 0
    assert stats["stored_row_reconciliation"]["reconciles"] is True
    assert anomalies[0]["hs_code_raw"] == "761699"
    file = staging / "year=2025" / "mm=01" / "part-00000.parquet"
    table = pq.ParquetFile(file).read()
    assert table.num_rows == 1
    row = table.to_pylist()[0]
    assert row["hs10"] == "0101219000"
    assert row["hs8"] == "01012190"
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


def test_summary_difference_policy_allows_only_small_weight_rounding():
    fact = {
        "export_usd": 100,
        "export_weight_kg": 1005,
        "import_usd": 50,
        "import_weight_kg": 503,
        "trade_balance_usd": 50,
    }
    summary = {
        "export_usd": 100,
        "export_weight_kg": 1000,
        "import_usd": 50,
        "import_weight_kg": 500,
        "trade_balance_usd": 50,
    }
    fatal, rounding = normalize.classify_summary_differences(fact, summary, fact_rows=10)
    assert fatal == {}
    assert rounding == {"export_weight_kg": 5, "import_weight_kg": 3}

    summary["export_usd"] = 99
    fatal, _ = normalize.classify_summary_differences(fact, summary, fact_rows=10)
    assert fatal == {"export_usd": 1}

    summary["export_usd"] = 100
    summary["export_weight_kg"] = 900
    fatal, _ = normalize.classify_summary_differences(fact, summary, fact_rows=10)
    assert fatal == {"export_weight_kg": 105}


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


def test_hsk_revision_map_is_applied_without_dropping_unknown_codes(tmp_path: Path):
    _write_source(
        tmp_path,
        "US",
        "202501",
        "202501",
        "2026-01-01T00:00:00+00:00",
        _xml("US", "202501", [("0101219000", 10, 0), ("9999999999", 5, 0)]),
    )
    sources, _ = normalize.discover_successful_sources(tmp_path, {"US"})
    selected, _ = normalize.select_sources_by_country_month(sources)
    staging = tmp_path / "normalized"
    revisions = {2025: {"0101219000": "HSK-2025"}}
    stats, anomalies = normalize.normalize_sources(
        normalize.selected_assignments(selected), staging, revisions
    )
    assert not anomalies
    assert stats["hsk_reference_unknown_rows"] == 1
    assert stats["hsk_reference_unknown_unique"] == 1
    table = pq.ParquetFile(staging / "year=2025" / "mm=01" / "part-00000.parquet").read()
    rows = {row["hs10"]: row for row in table.to_pylist()}
    assert rows["0101219000"]["hs_revision"] == "HSK-2025"
    assert rows["9999999999"]["hs_revision"] is None


def test_negative_weight_is_preserved_but_negative_amount_is_fatal():
    negative_weight = ET.fromstring(
        "<item><expDlr>10</expDlr><expWgt>-3</expWgt><impDlr>2</impDlr>"
        "<impWgt>1</impWgt><balPayments>8</balPayments></item>"
    )
    row = normalize.canonical_row(negative_weight, "US", "202501", "0101219000")
    assert row["export_weight_kg"] == -3
    assert row["export_usd"] == 10

    negative_amount = ET.fromstring(
        "<item><expDlr>-1</expDlr><expWgt>1</expWgt><impDlr>0</impDlr>"
        "<impWgt>0</impWgt><balPayments>-1</balPayments></item>"
    )
    try:
        normalize.canonical_row(negative_amount, "US", "202501", "0101219000")
    except ValueError as exc:
        assert str(exc) == "negative amount"
    else:
        raise AssertionError("negative monetary amount must remain fatal")
