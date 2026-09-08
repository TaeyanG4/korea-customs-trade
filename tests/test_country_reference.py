import pytest

from scripts.build_country_reference import build_reference


def test_build_reference_keeps_unmatched_kcs_code_without_guessing():
    kcs = [
        {"country_code": "US", "country_name_ko": "미국", "kcs_source_row": "1"},
        {"country_code": "Z1", "country_name_ko": "국제통화기금", "kcs_source_row": "2"},
    ]
    un = {
        "US": {
            "country_name_en": "United States of America",
            "un_m49": "840",
            "iso_alpha3": "USA",
        }
    }
    rows = build_reference(kcs, un, "1.3")
    assert rows[0]["country_name_en"] == "United States of America"
    assert rows[0]["un_match_status"] == "matched_current_un"
    assert rows[1]["country_name_en"] == ""
    assert rows[1]["un_match_status"] == "unmatched_kcs_code"
    assert rows[1]["country_code"] == "Z1"


def test_build_reference_rejects_duplicate_kcs_codes():
    kcs = [
        {"country_code": "US", "country_name_ko": "미국", "kcs_source_row": "1"},
        {"country_code": "US", "country_name_ko": "미국", "kcs_source_row": "2"},
    ]
    with pytest.raises(ValueError, match="Duplicate KCS country code"):
        build_reference(kcs, {}, "1.3")
