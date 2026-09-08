from datetime import date
from pathlib import Path

import collector


def test_latest_stable_month_before_publication_day():
    assert collector.latest_stable_month(date(2026, 9, 8)) == "202607"


def test_latest_stable_month_after_publication_day():
    assert collector.latest_stable_month(date(2026, 9, 16)) == "202608"


def test_annual_windows_split_only_on_calendar_year():
    windows = collector.annual_windows("201211", "201302")
    assert [(w.start, w.end) for w in windows] == [
        ("201211", "201212"),
        ("201301", "201302"),
    ]


def test_load_country_codes_and_subset(tmp_path: Path):
    p = tmp_path / "countries.csv"
    p.write_text("country_code,country_name_ko\nUS,미국\nCN,중국\n", encoding="utf-8")
    assert collector.load_country_codes(p) == ["US", "CN"]
    assert collector.load_country_codes(p, ["CN"]) == ["CN"]


def test_build_roots_year_country_order():
    windows = collector.annual_windows("202501", "202602")
    roots = collector.build_roots(["US", "CN"], windows, "year-country")
    assert [(c, w.start, w.end) for c, w in roots] == [
        ("US", "202501", "202512"),
        ("CN", "202501", "202512"),
        ("US", "202601", "202602"),
        ("CN", "202601", "202602"),
    ]
