import release_qa


def test_bad_unicode_reason_catches_replacement_and_controls():
    assert release_qa.bad_unicode_reason("정상 한글") is None
    assert release_qa.bad_unicode_reason("깨짐\ufffd") == "replacement_character"
    assert release_qa.bad_unicode_reason("bad\x00text") == "nul_character"


def test_hangul_detector_distinguishes_mojibake_like_text():
    assert release_qa.has_hangul("농가 사육용")
    assert not release_qa.has_hangul("Other")
    assert not release_qa.has_hangul("\u6e72??")
