# 한국 관세 수출입 2012–2026 — HSK 10자리 상품 수준

![Korea Customs Trade Kaggle banner](assets/korea_customs_trade_kaggle_banner.jpg)

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

## API 호출 한도 전략

공공데이터포털 공식 페이지 기준 개발계정의 신청 가능 트래픽은 **일 10,000회**입니다. 같은 페이지에는 **활용사례 등록 후 운영계정으로 트래픽 증가 신청 가능**하다고 명시되어 있으며, 이 관세청 API의 운영단계는 심의승인입니다.

이 프로젝트는 호출량을 다음 원칙으로 관리합니다.

- 성공하는 경우 `country × year` 1회 요청을 우선합니다. 약 240개국 × 15년이면 root 요청은 약 3,600회입니다.
- 성공하는 요청을 미리 quarter/month로 쪼개지 않습니다. adaptive split은 대용량 응답/timeout의 fallback으로만 사용합니다.
- 공공데이터포털 gateway reason code `22` (`LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR`)가 반환되면 collector는 추가 호출을 낭비하지 않고 즉시 중단합니다. 성공한 manifest는 그대로 checkpoint/resume에 사용됩니다.
- pilot에서 adaptive split 비율이 높아 일 10,000회를 넘길 가능성이 확인되면 production backfill 전에 운영계정/트래픽 증설을 신청합니다.
- 플랫폼 한도 우회를 목적으로 여러 개인계정이나 여러 키를 돌려쓰지 않습니다.

공식 파일데이터 `관세청_월별_품목별_국가별 수출입실적`은 보조 검증자료로는 사용할 수 있지만 공개 설명상 2021~2023년 HS4 자료이므로 이 프로젝트의 HSK10 Source of Truth를 대체하지 않습니다.

## Windows PowerShell 실행

```powershell
cd H:\dev\kaggle-data\korea-customs-trade
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:KCS_SERVICE_KEY='YOUR_DATA_GO_KR_SERVICE_KEY'
```

또는 프로젝트 루트의 로컬 `.env` 파일에 다음처럼 저장할 수 있습니다.

```text
KCS_SERVICE_KEY=YOUR_DATA_GO_KR_SERVICE_KEY
```

collector는 프로세스 환경변수에 키가 없을 때 `.env`를 자동으로 읽습니다. `.env`는 Git에서 제외됩니다.

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
