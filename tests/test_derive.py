import pyarrow as pa

import derive
import normalize


def test_hs6_aggregate_is_local_prefix_sum():
    rows = [
        {
            "month": "202501",
            "country_code": "US",
            "hs10": "0101211000",
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
