import pyarrow as pa

import derive
import normalize


def test_hs6_aggregate_is_local_prefix_sum():
    rows = [
        {
            "month": "202501",
            "country_code": "US",
            "hs10": "0101211000",
            "hs8": "01012110",
            "hs6": "010121",
            "hs4": "0101",
            "hs2": "01",
            "export_usd": 10,
            "export_weight_kg": 1,
            "import_usd": 2,
            "import_weight_kg": 1,
            "trade_balance_usd": 8,
            "hs_revision": None,
        },
        {
            "month": "202501",
            "country_code": "US",
            "hs10": "0101219000",
            "hs8": "01012190",
            "hs6": "010121",
            "hs4": "0101",
            "hs2": "01",
            "export_usd": 20,
            "export_weight_kg": 2,
            "import_usd": 5,
            "import_weight_kg": 1,
            "trade_balance_usd": 15,
            "hs_revision": None,
        },
    ]
    table = pa.Table.from_pylist(rows, schema=normalize.SCHEMA)
    out = derive.aggregate_table(table, 6)
    assert out.num_rows == 1
    row = out.to_pylist()[0]
    assert row["hs6"] == "010121"
    assert row["hs4"] == "0101"
    assert row["hs2"] == "01"
    assert row["export_usd"] == 30
    assert row["import_usd"] == 7
    assert row["trade_balance_usd"] == 23


def test_hs4_and_hs2_totals_match_input():
    rows = []
    for hs10, exp, imp in [("0101211000", 10, 2), ("0101290000", 20, 5), ("0201100000", 30, 10)]:
        rows.append(
            {
                "month": "202501",
                "country_code": "US",
                "hs10": hs10,
                "hs8": hs10[:8],
                "hs6": hs10[:6],
                "hs4": hs10[:4],
                "hs2": hs10[:2],
                "export_usd": exp,
                "export_weight_kg": 1,
                "import_usd": imp,
                "import_weight_kg": 1,
                "trade_balance_usd": exp - imp,
                "hs_revision": None,
            }
        )
    table = pa.Table.from_pylist(rows, schema=normalize.SCHEMA)
    expected = derive.measure_totals_arrow(table)
    for level in [4, 2]:
        out = derive.aggregate_table(table, level)
        assert derive.measure_totals_arrow(out) == expected


def test_hs8_is_supported_and_keeps_separate_prefixes():
    rows = []
    for hs10, exp in [("0101211000", 10), ("0101219000", 20)]:
        rows.append(
            {
                "month": "202501",
                "country_code": "US",
                "hs10": hs10,
                "hs8": hs10[:8],
                "hs6": hs10[:6],
                "hs4": hs10[:4],
                "hs2": hs10[:2],
                "export_usd": exp,
                "export_weight_kg": 1,
                "import_usd": 0,
                "import_weight_kg": 0,
                "trade_balance_usd": exp,
                "hs_revision": "HSK-2025",
            }
        )
    table = pa.Table.from_pylist(rows, schema=normalize.SCHEMA)
    out = derive.aggregate_table(table, 8)
    assert out.num_rows == 2
    assert {row["hs8"] for row in out.to_pylist()} == {"01012110", "01012190"}


def test_short_source_residual_maps_only_to_safe_levels():
    rows = [
        {
            "month": "202501",
            "country_code": "US",
            "hs10": "7616991000",
            "hs8": "76169910",
            "hs6": "761699",
            "hs4": "7616",
            "hs2": "76",
            "export_usd": 100,
            "export_weight_kg": 10,
            "import_usd": 0,
            "import_weight_kg": 0,
            "trade_balance_usd": 100,
            "hs_revision": "HSK-2025",
        }
    ]
    table = pa.Table.from_pylist(rows, schema=normalize.SCHEMA)
    residual = {
        "reason": "non_hs10_code",
        "month": "202501",
        "requested_country": "US",
        "hs_code_raw": "761699",
        "export_usd": 7,
        "export_weight_kg": 2,
        "import_usd": 1,
        "import_weight_kg": 1,
        "trade_balance_usd": 6,
    }
    hs6 = derive.aggregate_table(table, 6, [residual]).to_pylist()[0]
    assert hs6["export_usd"] == 107
    assert hs6["residual_export_usd"] == 7
    assert hs6["exception_row_count"] == 1
    assert hs6["has_residual"] is True

    hs8 = derive.aggregate_table(table, 8, [residual]).to_pylist()[0]
    assert hs8["export_usd"] == 100
    assert hs8["residual_export_usd"] == 0
    assert hs8["exception_row_count"] == 0
