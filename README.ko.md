# 한국 관세 수출입 2012–2026 — HSK 10자리 상품 수준

[English README](README.md)

이 저장소는 관세청 공식 공공데이터를 기반으로 재현 가능하고 업데이트 가능한 Kaggle 데이터 제품을 구축하기 위한 프로젝트입니다. 최종 Source of Truth의 grain은 다음과 같습니다.

`month × partner_country × HSK10`

한국 HSK **10자리**를 원천 grain으로 보존하고, `hs6`, `hs4`, `hs2`는 HSK10 prefix에서 로컬 파생합니다. HS2/4/6을 API에서 별도로 중복 수집하지 않습니다.

## 현재 단계

현재는 **API pilot 단계**입니다. 전체 backfill 전에 다음 핵심 가정을 실제 API 호출로 검증합니다.

> `cntyCd`와 조회기간만 지정하고 `hsSgn`을 생략했을 때, 해당 국가의 월별 전체 HSK10 거래 row가 반환되는가?

첫 live test는 **US × 2025**입니다. 이후 pilot matrix는 다음과 같습니다.

- 국가: `US`, `CN`, `JP`, `VN`, `DE`
- 연도: `2012`, `2017`, `2022`, `2025`

이 pilot을 통과하기 전에는 full crawl을 진행하지 않습니다.

## 공식 API

- 관세청 품목별 국가별 수출입실적(GW)
- Endpoint: `https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList`
- 주요 파라미터: `serviceKey`, `strtYymm`, `endYymm`, `cntyCd`
- pilot에서는 핵심 가설 검증을 위해 `hsSgn`을 의도적으로 생략합니다.

## Pilot이 기록하는 항목

모든 요청은 raw 응답을 보존하고, 검증·재현·resume에 필요한 메타데이터를 남깁니다.

- HTTP status 및 API result code/message
- 원본 응답 byte 수와 SHA-256
- gzip 압축 raw XML
- 전체 item 수와 fact row 수
- HS code 길이 분포
- 숫자형 HSK10 준수 여부
- 요청 월 coverage
- `(month, country, hs10)` duplicate
- zero-trade row
- 음수 금액/중량 row
- `trade_balance == export - import` 검증
- 국가코드 mismatch
- 동일 HSK10의 한국어 품목명 variation
- elapsed time 및 retry 횟수

`data.go.kr` 서비스 키는 manifest에 기록하지 않습니다.

## Adaptive split

기본 논리 수집 단위는 `country × year`입니다. 네트워크/응답크기 계열의 retry 가능한 실패가 발생하면 자동으로 분할합니다.

```text
country × year
  -> country × quarter
      -> country × month
```

인증 오류, 잘못된 파라미터, 명시적인 API 오류는 split으로 숨기지 않고 그대로 실패로 남깁니다.

## Windows PowerShell 실행

```powershell
cd H:\dev\kaggle-data\korea-customs-trade
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:KCS_SERVICE_KEY='YOUR_DATA_GO_KR_SERVICE_KEY'
```

첫 pilot 실행:

```powershell
.\run_us_2025.ps1
```

생성된 pilot report를 검토한 뒤에만 matrix를 실행합니다.

```powershell
.\run_matrix.ps1
```

## 출력 구조

```text
data/
  raw/
    year=2025/
      country=US/
        response_202501-202512.xml.gz
  audits/
    manifests/
      year=2025/
        country=US/
          request_202501-202512.json
    coverage/
      pilot_results.json
      pilot_results.csv
      pilot_report.md
      hs_name_inventory.csv
      hs_name_changes.csv
```

raw 및 생성 데이터는 기본적으로 Git에서 제외합니다. GitHub에는 코드, 설정 템플릿, 문서, 재현 가능한 파이프라인 로직을 백업하고 서비스 키나 대용량 raw 응답은 올리지 않습니다.

## 테스트

```powershell
pytest -q
```

## Pilot 통과 조건

논리적 country-year는 다음 조건을 모두 만족해야 `PASS`입니다.

- effective leaf request 전부 성공
- fact row 1개 이상
- 모든 fact row의 HS code가 숫자형 10자리
- 요청한 모든 월이 응답에 존재
- `(month, country, hs10)` duplicate 없음

Pilot `PASS`는 해당 요청에서 관찰된 API 동작을 검증하는 것입니다. 과거 모든 유효 HSK10 code가 완전하게 반환된다는 사실까지 증명하지는 않습니다. 공개 release 전에는 별도 공식 합계와 revision-aware HSK codebook을 이용한 reconciliation이 필요합니다.

## 예정 canonical fact schema

```text
month
country_code
hs10
hs6
hs4
hs2
export_usd
export_weight_kg
import_usd
import_weight_kg
trade_balance_usd
hs_revision
```

국가명과 긴 품목명은 가능하면 fact table에서 반복하지 않고 dimension으로 분리합니다.

## Kaggle 포지셔닝

목표 데이터셋명:

**South Korea Customs Trade 2012–2026 — 10-Digit Product Level**

핵심 메시지:

> South Korea's monthly customs trade at the full 10-digit HSK product level, across 200+ partner economies, with HS6/HS4/HS2 mappings and long-term history.
