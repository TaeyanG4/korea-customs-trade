import gzip
from pathlib import Path

import pilot


SAMPLE_XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode><resultMsg>normal service</resultMsg></header>
  <body><items>
    <item><year>total</year><statCd>-</statCd><hsCd>-</hsCd><statKor>-</statKor><expDlr>300</expDlr><expWgt>3</expWgt><impDlr>100</impDlr><impWgt>1</impWgt><balPayments>200</balPayments></item>
    <item><year>2025.01</year><statCd>US</statCd><hsCd>0101219000</hsCd><statKor>other</statKor><expDlr>10</expDlr><expWgt>1</expWgt><impDlr>0</impDlr><impWgt>0</impWgt><balPayments>10</balPayments></item>
    <item><year>2025.02</year><statCd>US</statCd><hsCd>0101219000</hsCd><statKor>other</statKor><expDlr>0</expDlr><expWgt>0</expWgt><impDlr>0</impDlr><impWgt>0</impWgt><balPayments>0</balPayments></item>
  </items></body>
</response>'''

QUOTA_XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<OpenAPI_ServiceResponse>
  <cmmMsgHeader>
    <errMsg>SERVICE ERROR</errMsg>
    <returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg>
    <returnReasonCode>22</returnReasonCode>
  </cmmMsgHeader>
</OpenAPI_ServiceResponse>'''


def test_parse_and_validate(tmp_path: Path):
    p = tmp_path / "x.xml.gz"
    with gzip.open(p, "wb") as f:
        f.write(SAMPLE_XML)
    m = pilot.parse_and_validate_gzip(p, "US", pilot.Window("202501", "202502"))
    assert m["api_result_code"] == "00"
    assert m["row_count"] == 3
    assert m["fact_row_count"] == 2
    assert m["total_row_count"] == 1
    assert m["hs_length_counts"] == {"10": 2}
    assert m["non_hs10_fact_rows"] == 0
    assert m["missing_months"] == []
    assert m["zero_trade_rows"] == 1
    assert m["balance_mismatch_rows"] == 0


def test_detects_duplicate_and_bad_hs(tmp_path: Path):
    xml = SAMPLE_XML.replace(
        b"</items>",
        b"<item><year>2025.01</year><statCd>US</statCd><hsCd>0101219000</hsCd><statKor>other</statKor><expDlr>10</expDlr><expWgt>1</expWgt><impDlr>0</impDlr><impWgt>0</impWgt><balPayments>10</balPayments></item>"
        b"<item><year>2025.02</year><statCd>US</statCd><hsCd>123456</hsCd><statKor>bad</statKor><expDlr>1</expDlr><expWgt>1</expWgt><impDlr>0</impDlr><impWgt>0</impWgt><balPayments>1</balPayments></item>"
        b"</items>",
    )
    p = tmp_path / "x.xml.gz"
    with gzip.open(p, "wb") as f:
        f.write(xml)
    m = pilot.parse_and_validate_gzip(p, "US", pilot.Window("202501", "202502"))
    assert m["duplicate_key_groups"] == 1
    assert m["duplicate_key_rows"] == 1
    assert m["non_hs10_fact_rows"] == 1


def test_parses_data_go_kr_gateway_quota_error(tmp_path: Path):
    p = tmp_path / "quota.xml.gz"
    with gzip.open(p, "wb") as f:
        f.write(QUOTA_XML)
    m = pilot.parse_and_validate_gzip(p, "US", pilot.Window("202501", "202512"))
    assert m["api_result_code"] == "22"
    assert m["api_result_msg"] == "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"
    assert m["fact_row_count"] == 0


def test_split_year_to_quarters():
    chunks = pilot.split_window(pilot.Window("202501", "202512"))
    assert [(x.start, x.end) for x in chunks] == [
        ("202501", "202503"),
        ("202504", "202506"),
        ("202507", "202509"),
        ("202510", "202512"),
    ]


def test_normalize_service_key():
    assert pilot.normalize_service_key("abc%2Bdef%3D%3D") == "abc+def=="


class FakeResponse:
    def __init__(self, chunks, status_code=200):
        self._chunks = chunks
        self.status_code = status_code
        self.headers = {"Content-Type": "application/xml"}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise pilot.requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def iter_content(self, chunk_size=1024):
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def test_stream_read_failure_is_retried_and_key_not_manifested(tmp_path: Path):
    first = FakeResponse([b"partial", pilot.requests.ConnectionError("read failed")])
    second = FakeResponse([SAMPLE_XML])
    session = FakeSession([first, second])
    outcome = pilot.download_one(
        session=session,
        service_key="SECRET+KEY==",
        country="US",
        window=pilot.Window("202501", "202502"),
        data_dir=tmp_path,
        connect_timeout=1,
        read_timeout=1,
        retries=1,
        force=True,
    )
    assert outcome.success is True
    assert outcome.retry_count == 1
    assert session.calls == 2
    assert first.closed and second.closed
    with gzip.open(outcome.raw_path, "rb") as f:
        assert f.read() == SAMPLE_XML
    manifest_text = Path(outcome.manifest_path).read_text(encoding="utf-8")
    assert "SECRET" not in manifest_text
    assert '"hsSgn_omitted": true' in manifest_text


def test_quota_response_is_classified_without_retry_or_split(tmp_path: Path):
    response = FakeResponse([QUOTA_XML])
    session = FakeSession([response])
    outcome = pilot.download_one(
        session=session,
        service_key="SECRET+KEY==",
        country="US",
        window=pilot.Window("202501", "202512"),
        data_dir=tmp_path,
        connect_timeout=1,
        read_timeout=1,
        retries=2,
        force=True,
    )
    assert outcome.success is False
    assert outcome.status == "quota_exceeded"
    assert outcome.api_result_code == "22"
    assert session.calls == 1
    assert pilot.should_split(outcome) is False


def test_logical_root_split_success():
    parent = pilot.RequestOutcome(
        country="US", window_start="202501", window_end="202512", split_level="year",
        success=False, status="transport_error"
    )
    children = []
    for start, end in [
        ("202501", "202503"),
        ("202504", "202506"),
        ("202507", "202509"),
        ("202510", "202512"),
    ]:
        months = pilot.months_in_window(pilot.Window(start, end))
        children.append(pilot.RequestOutcome(
            country="US", window_start=start, window_end=end, split_level="quarter",
            success=True, status="success", fact_row_count=100, response_bytes=1000,
            month_count=3, months_found=months, missing_months=[], hs_length_counts={"10": 100},
            parent_request="US:202501-202512"
        ))
    r = pilot.logical_root_summary("US", pilot.Window("202501", "202512"), [parent, *children])
    assert r["status"] == "split_success"
    assert r["verdict"] == "PASS"
    assert r["month_count"] == 12
    assert r["fact_row_count"] == 400
