import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from hsk_reference import (
    SCHEMA,
    YearIndex,
    parse_chapter_html,
    parse_year_index,
    review_duplicate_name_variants,
)


INDEX_HTML = """
<form>
  <input name="aplyYy" value="2022" />
  <input name="sctYear" value="20220101" />
  <input name="hstdYear" value="20220101" />
  <input name="hstdCd" value="02" />
  <input name="hstdCd" value="01" />
  <input name="hstdCd" value="01" />
</form>
"""


CHAPTER_HTML = """
<table><tbody id="tblLstBody">
  <tr>
    <td><input name="hsSgn_Mn" value="010121" /></td>
    <td class="hlzoneWrd">국제 6자리</td><td class="hlzoneWrd">HS6 heading</td>
  </tr>
  <tr>
    <td><input name="hsSgn_Mn" value="0101211000" /></td>
    <td>x</td><td>y</td>
    <td class="hlzoneWrd"><a>농가 사육용</a></td>
    <td class="hlzoneWrd"><a>For farm breeding</a></td>
  </tr>
  <tr>
    <td><input name="hsSgn_Mn" value="0101219000" /></td>
    <td>x</td><td>y</td>
    <td class="hlzoneWrd">기타</td>
    <td class="hlzoneWrd">Other</td>
  </tr>
</tbody></table>
"""


def test_parse_year_index():
    idx = parse_year_index(INDEX_HTML, 2022)
    assert idx.year == 2022
    assert idx.clip_sct_year == "20220101"
    assert idx.clip_hstd_year == "20220101"
    assert idx.chapters == ("01", "02")


def test_parse_chapter_keeps_only_exact_hsk10():
    idx = YearIndex(2022, "20220101", "20220101", ("01",))
    rows = parse_chapter_html(CHAPTER_HTML, idx, "01")
    assert [r["hs10"] for r in rows] == ["0101211000", "0101219000"]
    assert rows[0]["hs8"] == "01012110"
    assert rows[0]["hs6"] == "010121"
    assert rows[0]["name_ko"] == "농가 사육용"
    assert rows[0]["name_en"] == "For farm breeding"
    assert rows[0]["hs_revision"] == "HSK-2022"
    assert rows[0]["name_ko"].encode("unicode_escape") == b"\\ub18d\\uac00 \\uc0ac\\uc721\\uc6a9"


def test_parse_chapter_rejects_cross_chapter_code():
    idx = YearIndex(2022, "20220101", "20220101", ("01",))
    bad = CHAPTER_HTML.replace("0101211000", "0201211000")
    try:
        parse_chapter_html(bad, idx, "01")
    except ValueError as exc:
        assert "out-of-prefix" in str(exc)
    else:
        raise AssertionError("expected out-of-prefix HSK10 to fail")


def test_parse_chapter_resolves_compatible_duplicate_label():
    idx = YearIndex(2012, "20120101", "20120101", ("71",))
    html = """
    <table><tbody id="tblLstBody">
      <tr>
        <td><input name="hsSgn_Mn" value="7102390000" /></td>
        <td class="hlzoneWrd">기타</td><td class="hlzoneWrd">Other</td>
      </tr>
      <tr>
        <td><input name="hsSgn_Mn" value="7102390000" /></td>
        <td class="hlzoneWrd">기타(공업용 다이아몬드와 원석을 제외한 가공된 다이아몬드)</td>
        <td class="hlzoneWrd">Other</td>
      </tr>
    </tbody></table>
    """
    audit = []
    rows = parse_chapter_html(html, idx, "71", audit)
    assert len(rows) == 1
    assert rows[0]["name_ko"].startswith("기타(")
    assert rows[0]["name_en"] == "Other"
    assert len(audit) == 1
    assert audit[0]["resolution"] == "prefer_more_specific_compatible_label"


def test_parse_chapter_preserves_contradictory_duplicate_label_for_review():
    idx = YearIndex(2012, "20120101", "20120101", ("71",))
    html = """
    <table><tbody id="tblLstBody">
      <tr>
        <td><input name="hsSgn_Mn" value="7102390000" /></td>
        <td class="hlzoneWrd">기타</td><td class="hlzoneWrd">Other</td>
      </tr>
      <tr>
        <td><input name="hsSgn_Mn" value="7102390000" /></td>
        <td class="hlzoneWrd">완전히 다른 품명</td><td class="hlzoneWrd">Different</td>
      </tr>
    </tbody></table>
    """
    audit = []
    rows = parse_chapter_html(html, idx, "71", audit)
    assert len(rows) == 1
    assert rows[0]["name_ko"] == "기타"
    assert rows[0]["name_en"] == "Other"
    assert len(audit) == 1
    assert audit[0]["resolution"] == "prefer_first_source_order_pending_adjacent_year_review"


def test_adjacent_year_review_can_rewrite_transition_year(tmp_path):
    code = "6815910000"

    def row(year, ko, en):
        return {
            "reference_year": year,
            "hs_revision": f"HSK-{year}",
            "valid_from": f"{year}-01-01",
            "valid_to": f"{year}-12-31",
            "clip_sct_year": f"{year}0101",
            "clip_hstd_year": f"{year}0101",
            "hs10": code,
            "hs8": code[:8],
            "hs6": code[:6],
            "hs4": code[:4],
            "hs2": code[:2],
            "name_ko": ko,
            "name_en": en,
            "source": "test",
            "source_url": "https://example.test",
        }

    old = ("구 정의", "Old definition")
    new = ("신 정의", "New definition")
    for year, names in [(2021, old), (2022, old), (2023, new)]:
        d = tmp_path / f"year={year}"
        d.mkdir()
        pq.write_table(pa.Table.from_pylist([row(year, *names)], schema=SCHEMA), d / "hsk10.parquet")

    stats = [
        {
            "year": 2022,
            "duplicate_name_variants": [
                {
                    "hs10": code,
                    "first_source_name_ko": old[0],
                    "first_source_name_en": old[1],
                    "second_source_name_ko": new[0],
                    "second_source_name_en": new[1],
                    "selected_name_ko": old[0],
                    "selected_name_en": old[1],
                    "resolution": "prefer_first_source_order_pending_adjacent_year_review",
                }
            ],
        }
    ]
    result = review_duplicate_name_variants(stats, tmp_path)
    assert result == {"reviewed": 1, "resolved": 1, "unresolved": 0, "annual_name_rewrites": 1}
    reviewed = stats[0]["duplicate_name_variants"][0]
    assert reviewed["resolution"] == "adjacent_year_validated_revision_transition_second_is_current"
    table = pq.ParquetFile(tmp_path / "year=2022" / "hsk10.parquet").read()
    assert table["name_ko"].to_pylist() == [new[0]]
    assert table["name_en"].to_pylist() == [new[1]]
