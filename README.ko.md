# 한국 관세 수출입 2012–2026 — HSK 10자리 상품 수준

![Korea Customs Trade Kaggle banner](assets/korea_customs_trade_kaggle_banner.jpg)

[English README](README.md)

[데이터 모델 / 릴리스 구조](DATA_MODEL.ko.md)

이 저장소는 관세청 공식 공공데이터를 기반으로 재현 가능하고 업데이트 가능한 Kaggle 데이터 제품을 구축하기 위한 프로젝트입니다. 최종 Source of Truth의 grain은 다음과 같습니다.

`month × partner_country × HSK10`

한국 HSK **10자리**를 원천 grain으로 보존하고, `hs8`, `hs6`, `hs4`, `hs2`는 HSK10 prefix에서 로컬 파생합니다. HS2/4/6/8을 API에서 별도로 중복 수집하지 않습니다.

## 현재 단계

API pilot, 국가코드 검증, production collector, normalization pipeline, full historical backfill, 공식 연도별 HSK reference 수집, release QA, private-first Kaggle 검증, public Dataset 공개, public starter Notebook 공개까지 완료했습니다. 현재는 마지막 **Usability 10.00** gap을 닫는 단계입니다. 최초 핵심 가정은 다음이었습니다.

> `cntyCd`와 조회기간만 지정하고 `hsSgn`을 생략했을 때, 해당 국가의 월별 전체 HSK10 거래 row가 반환되는가?

첫 live test는 **US × 2025**였고, 완료된 pilot matrix는 다음과 같습니다.

- 국가: `US`, `CN`, `JP`, `VN`, `DE`
- 연도: `2012`, `2017`, `2022`, `2025`

이 gate를 통과한 뒤 full crawl을 진행했으며, 현재 historical backfill은 완료된 상태입니다.

### 로드맵 진행 상황

현재 단계는 **12/12 — public Kaggle release 공개 완료, Usability 10.00 후속 작업 진행 중**입니다. full historical backfill은 4,035/4,035 country-year root가 전부 성공했고 unresolved failure는 0이며 총 22,351,483 fact rows를 수집했습니다. Stage 11은 strict HSK10 22,351,430 rows와 non-HSK10 원천 예외 53 rows를 만들었고 canonical duplicate는 0, 최종 `release_gate_pass=true`입니다. 공식 CLIP 2012–2026 연도별 HSK reference는 총 178,911 annual HSK10 rows이며 국문/영문 품명 누락과 미해결 duplicate-label review가 없습니다.

Kaggle Dataset `taeyangg4/south-korea-customs-trade-hsk10`은 현재 **Public**이며 Version 2가 `Ready`, 관측 Usability는 **8.24/10**입니다. Public starter Notebook `taeyangg4/south-korea-trade-in-5-minutes-hs6-quickstart`는 Version 3까지 Kaggle runtime에서 정상 완료됐고 Dataset mount auto-discovery, traceback 없음, 한글 glyph warning 없음까지 확인했습니다. Kaggle Usability 세부값을 직접 확인한 결과 현재 감점은 file description과 column description 두 항목뿐이며 나머지 score component는 모두 완료 상태입니다.

최종 제품 목표는 **Kaggle Usability 10.00 + Dataset medal**입니다. 원천 데이터를 과도하게 정제하지 않고, 공식성·재현성·분석 편의성·문서화·지속 업데이트·한글 무결성을 중심으로 완성도를 높입니다.

다만 matrix에서 중요한 원천 데이터 예외를 확인했습니다. 1,379,734개 fact row 중 5개가 10자리가 아니었으며, 6자리 4건과 9자리 1건입니다. 해당 코드를 별도 API 조회해도 동일하게 재현되어 파서 오류가 아니라 upstream API/원천 데이터 예외로 확인했습니다. 이 row들은 raw XML과 `non_hs10_rows.csv`에 그대로 보존하며, canonical HSK10에는 절대 zero-padding하거나 추정 매핑하지 않습니다.

공식 KCS 조회코드 workbook에서 **269개 고유 국가코드**를 확보했습니다. 269개 전부를 2025-01 API로 검증한 결과 모두 정상 `resultCode=00`이었고, 236개는 해당 월 거래 row가 있었으며 33개는 거래가 없었습니다. 269개 전체에서 **128,207 fact rows**가 관측됐고 모두 숫자형 HSK10이었습니다. full-history planning band는 약 **2,200만~3,500만 rows**, production root request는 **4,035회**입니다.

최종 Stage-11 partitioned output은 HSK10 **22,351,430 rows / 441,335,631 bytes**, HS8 **20,576,865 / 353,521,769**, HS6 **16,059,132 / 257,080,829**, HS4 **7,234,105 / 124,721,647**, HS2 **1,446,045 / 29,122,656**입니다. 다섯 level 모두 2012-01~2026-07의 175개 월 partition을 가집니다.

Stage 11 전체 재빌드는 다음 명령으로 재현할 수 있습니다.

```powershell
.\run_stage11.ps1
```

이 명령은 full country-month coverage를 요구하고, annual HSK revision 연결, HS8/HS6/HS4/HS2 residual-aware 집계, 한글/UTF-8 release gate까지 순차 실행합니다.

Kaggle 업로드용 package는 다음 명령으로 만듭니다.

```powershell
.\run_build_release.ps1
```

Git Bash에서는 `bash ./run_build_release.sh`를 사용합니다. Builder는 grain별 단일 Parquet 5개, 최신월 HS6 CSV preview, reference/audit, checksum manifest, Kaggle file/column metadata, provenance와 문서를 Git에서 제외된 `release/kaggle/`에 생성합니다.

국가코드 authority 정책은 다음과 같습니다.

- `country_code`, `country_name_ko`: 관세청 `관세청조회코드_v1.3.xlsx`
- 영문명/M49/alpha3: UN Statistics Division M49의 alpha-2 정확 일치만 보강
- 매칭되지 않는 KCS 코드는 영문명을 추정하지 않고 그대로 유지

## Revision-aware HSK reference

10단계의 역사 HSK 기준자료는 관세청 CLIP의 한국 연도별 관세율표를 사용합니다. CLIP은 프로젝트 대상기간의 연도별 한국 관세율표와 계층형 품목정보, 국문/영문 품명을 제공합니다.

`hsk_reference.py`는 CLIP 원문 HTML을 연도/류별 gzip cache로 보존하고 resume하며, 정확한 숫자형 HSK10만 파싱해 연도별 및 통합 Parquet reference를 생성합니다.

```powershell
python .\hsk_reference.py probe --year 2022 --chapter 01
.\run_hsk_reference.ps1
```

첫 live probe는 2022년 제1류에서 HSK10 69개를 추출했고 국문명/영문명 누락은 모두 0이었습니다. 2012–2026 전체 수집도 완료되어 178,911 annual HSK10 rows, 국문명 누락 0, 영문명 누락 0, annual key 중복 0, prefix mismatch 0을 확인했습니다. 동일 코드 명칭 variant는 3건만 관측됐고, 2012년 2건은 더 구체적인 compatible wording을 선택했으며 2022년 revision-boundary 1건은 2021/2023 인접 연도와 자동 비교해 해결했습니다. `HSK-YYYY`는 CLIP의 **공식 연도판**을 의미하며, 연도 선택 화면에서 확인할 수 없는 연중 법적 개정 경계를 임의 추정하지 않습니다.

## Production collector

대규모 수집 전 전체 계획은 dry-run으로 확인합니다.

```powershell
python .\collector.py --dry-run backfill
```

2026-09-08 기준 기본 계획은 `201201–202607`, 공식 국가코드 269개, calendar-year window 15개, **4,035 root requests**입니다. 안정월은 관세청이 전월 자료를 매월 15일경 현행화한다는 특성을 고려해 15일 이전에는 전전월, 16일 이후에는 전월을 사용합니다.

완료된 full backfill은 다음 명령으로 재현할 수 있습니다.

```powershell
.\run_backfill.ps1
```

월간 revision refresh는 최신 안정월과 직전 12개월, 총 13개월을 강제 재수집합니다.

```powershell
.\run_refresh.ps1
```

smoke test에는 `--countries`, `--max-roots`, `--dry-run`을 사용할 수 있습니다. production run manifest는 `data/audits/runs/`에 기록되며 서비스키는 포함하지 않습니다.

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

- 성공하는 경우 `country × calendar-year window` 1회 요청을 우선합니다. 공식 목록 기준 현재 계획은 269개 코드 × 15개 window = **4,035 root requests**입니다.
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
  normalized/
    hs10/
      year=2025/
        mm=01/
          part-00000.parquet
  derived/
    hs8/year=2025/mm=01/part-00000.parquet
    hs6/year=2025/mm=01/part-00000.parquet
    hs4/year=2025/mm=01/part-00000.parquet
    hs2/year=2025/mm=01/part-00000.parquet
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
    normalization/
      source_selection.csv
      normalization_manifest.json
      normalization_anomalies.csv
    derivation/
      derivation_manifest.json
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

## Canonical fact schema

```text
month
country_code
hs10
hs8
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

`month`는 `YYYYMM` 문자열입니다. `hs8`, `hs6`, `hs4`, `hs2`는 `hs10`의 strict prefix입니다. `hs_revision`은 동일 연도의 공식 KCS CLIP edition에 코드가 존재할 때만 채우며, 미매칭 trade fact는 삭제하거나 추정하지 않고 null revision과 audit를 유지합니다.

Normalization은 raw 요청이 겹쳐도 `(country, month)`별로 가장 최근 성공 manifest를 1개만 선택합니다. 따라서 월간 revision refresh에서 과거 row가 삭제된 경우에도 append-only stale row가 남지 않고 전체 rebuild 시 정상적으로 사라집니다.

장기 데이터 제품 구조는 [`DATA_MODEL.ko.md`](DATA_MODEL.ko.md)에 고정해 두었습니다. 최종 분석가용 release는 HS2/HS4/HS6/HS8/HSK10 grain을 서로 분리해 제공합니다. Canonical HSK10은 숫자형 정확한 10자리만 유지하고 짧은 upstream code는 별도 quarantine하며 절대 padding/추정하지 않습니다. Residual-aware aggregate는 관측 prefix만으로 정확히 식별 가능한 hierarchy level에만 예외 금액을 포함합니다.

## Kaggle 포지셔닝

목표 데이터셋명:

**South Korea Customs Trade 2012–2026 — 10-Digit Product Level**

핵심 메시지:

> South Korea's monthly customs trade at the full 10-digit HSK product level, across 200+ partner economies, with HS6/HS4/HS2 mappings and long-term history.
