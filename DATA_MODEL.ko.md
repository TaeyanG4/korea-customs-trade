# 데이터 모델 및 Kaggle 릴리스 구조

[English](DATA_MODEL.md)

이 문서는 프로젝트의 장기 설계 기준입니다. 대화 context가 compact되거나 나중에 구현 결정을 다시 검토할 때도 이 문서를 Source of Truth로 사용합니다.

## 1. 수집 원칙

관세청 품목별 국가별 API는 가능한 가장 세밀한 원천 수준에서 한 번만 수집합니다.

`country × calendar-year`, `hsSgn` 생략

HS2/HS4/HS6/HS8/HSK10을 각각 별도 API crawl해서 메인 데이터셋을 만들지 않습니다. 동일한 revision 시점의 원천 응답 하나에서 모든 분석용 level을 로컬 파생합니다.

Raw XML은 감사 가능한 원천 증거이며 request manifest, hash, timestamp와 함께 로컬에 보존합니다.

## 2. Canonical 원천 grain

메인 fact table은 엄격하게 다음 grain을 유지합니다.

`month × country_code × HSK10`

숫자형 정확한 10자리 코드만 canonical HSK10에 포함합니다. 짧거나 비정상인 코드를 zero-padding하거나 10자리 코드로 추정하지 않습니다.

Canonical 컬럼:

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

`hs8`, `hs6`, `hs4`, `hs2`는 유효 HSK10 prefix에서 파생합니다. 국제 공통 표준은 HS6까지이며 HS8/HSK10은 한국 국가 확장 세부 수준으로 취급합니다.

## 3. 원천 mixed-granularity 예외

실제 API pilot에서 정상 HSK10 하위코드와 동시에 6자리/9자리 같은 짧은 거래 row가 극소수 관측됐습니다. 이는 parser 오류나 단순 중복 aggregate가 아니라 원천 데이터의 별도 거래 row입니다.

정책:

- raw XML을 변경하지 않고 보존;
- 구조화된 exception table로 격리;
- 누락 HSK10을 임의 추정하지 않음;
- reconciliation에서 금액/중량 영향을 반드시 표시;
- prefix만으로 해당 상위 level을 정확히 식별할 수 있을 때만 그 level 집계에 포함.

목표 예외 파일:

`source_code_exceptions.parquet`

권장 컬럼:

```text
month
country_code
raw_hs_code
raw_hs_length
name_ko
export_usd
export_weight_kg
import_usd
import_weight_kg
trade_balance_usd
source_manifest
source_raw_path
exception_reason
```

## 4. 분석가용 level

Kaggle에는 서로 다른 HS level을 한 테이블에 섞기보다 level별 ready-to-use 파일을 제공합니다.

```text
trade_hs10_monthly.parquet
trade_hs8_monthly.parquet
trade_hs6_monthly.parquet
trade_hs4_monthly.parquet
trade_hs2_monthly.parquet
source_code_exceptions.parquet
hs_code_reference.parquet
country_reference.csv
release_manifest.json
coverage_report.csv
README.md
DATA_DICTIONARY.md
METHODOLOGY.md
SOURCES.md
```

핵심 원칙은 **한 파일 = 한 분석 grain**입니다. HS2/4/6/8/10을 한 long table에 섞으면 사용자가 단순 합계할 때 같은 거래가 여러 hierarchy level에서 중복 합산될 수 있으므로 primary release 형식으로 사용하지 않습니다.

## 5. Residual-aware aggregation

원천 예외가 있을 때 HS2/4/6/8 파생 테이블의 완전성은 서로 다릅니다.

예:

```text
761699        172 USD   # 원천 6자리 residual
7616991000 165818 USD   # HSK10 child
7616999010   7075 USD   # HSK10 child
7616999090 1940201 USD  # HSK10 child
```

HS6에서는 6자리 residual을 `761699`에 정확하게 할당할 수 있으므로 다음처럼 완전한 합계를 만들 수 있습니다.

`total = HSK10 child 합 + direct source residual`

반면 6자리 residual을 특정 HS8 child로는 안전하게 배분할 수 없습니다. 비율 배분이나 임의 추정은 금지합니다.

권장 aggregate 컬럼:

```text
export_usd
import_usd
export_weight_kg
import_weight_kg
trade_balance_usd

export_usd_from_hsk10
import_usd_from_hsk10
export_usd_residual
import_usd_residual
source_row_count
exception_row_count
```

Residual을 추정 없이 전부 할당할 수 있는 level에서는 단순 `export_usd` / `import_usd`를 분석가 친화적인 완전 합계로 제공합니다. 배분 불가능 residual은 coverage metadata에서 명시합니다.

## 6. Level 의미

- **HS2**: 큰 상품군/거시 분석. 최소 2자리 이상 유효 prefix인 예외는 안전하게 매핑 가능.
- **HS4**: 산업/heading 분석. 최소 4자리 이상이면 안전하게 매핑 가능.
- **HS6**: 국제 비교 기본 세부 level. 원천 6자리 residual을 정확히 포함 가능.
- **HS8**: 한국 세부 prefix 분석. 8자리 미만 residual은 특정 HS8 child에 추정 배분하지 않음.
- **HSK10**: 한국 최종 세부 canonical fact. 정확한 숫자 10자리만 포함.

범용 분석에는 HS6를 기본 추천하고, 한국 제품/공급망 초정밀 분석에는 HSK10을 차별화 테이블로 제공합니다.

## 7. HSK revision 정책

HSK 정의는 시간에 따라 바뀔 수 있으므로 같은 숫자 HSK10이 모든 연도에서 동일 의미라고 가정하지 않습니다.

목표 HSK dimension:

```text
hs10
hs8
hs6
hs4
hs2
revision
name_ko
name_en
valid_from
valid_to
source
```

Revision/version은 공식 revision-aware source에서만 채웁니다. 공식 역사 정의가 확보되지 않는 부분은 API 관측 품목명을 보존하고 임의 추론하지 않습니다.

## 8. 국가 dimension

수집 code와 한글 국가는 관세청을 authoritative source로 사용합니다. UN M49 보강은 정확한 일치만 적용하며 관세청 고유 코드는 추정 영문명을 만들지 않고 그대로 유지합니다.

```text
country_code
country_name_ko
country_name_en
alpha3
m49
```

## 9. Revision-safe 월간 업데이트

공개 데이터셋은 append-only가 아닙니다. 매월:

1. 최신 안정월 수집;
2. 직전 12개월 재수집;
3. `(country, month)`별 가장 최신 성공 source 1개 선택;
4. 영향 기간 normalized fact 재생성;
5. rows added/removed/changed와 금액 revision 기록.

## 10. Release quality gate

공개 전 최소 조건:

- scheduled request 누락 0;
- unresolved API failure 0;
- canonical `(month,country_code,hs10)` duplicate 0;
- canonical HSK10 비정상 코드 0;
- month/partition mismatch 0;
- 음수 거래금액 0; 관세청 원천의 음수 중량은 0으로 보정하거나 삭제하지 않고 원값 그대로 보존하며 anomaly/warning으로 공개;
- 설명되지 않은 trade-balance mismatch 0;
- source row 수가 canonical + exception으로 reconciliation;
- exception/residual 금액 영향을 정량화;
- 가능한 범위에서 독립 공식 합계와 reconciliation;
- HSK revision coverage 및 unknown code 보고.

## 11. Kaggle 사용성 목표

목표는 단순히 가장 큰 한국 관세 파일을 만드는 것이 아니라 한국 관세 데이터를 매우 쉽게 분석할 수 있게 만드는 것입니다.

제품 목표는 **Kaggle Usability 10.00과 Dataset medal 획득**입니다. 이를 위해 원천 데이터를 과도하게 정제하거나 보기 좋은 값으로 임의 수정하지 않습니다. 대신 재현 가능한 공식 출처, 명확한 grain, ready-to-use Parquet, 데이터 사전/방법론, 안정적인 업데이트, 품질 audit에 집중합니다.

공개 대상의 한글 텍스트는 release blocker로 관리합니다. CSV/Markdown은 UTF-8 strict decode를 통과해야 하고, HSK/국가 한글명은 replacement character(`�`), NUL/제어문자, 디코딩 손상으로 한글이 사라진 행이 없어야 합니다. 원천 exception의 값은 손상되지 않은 한 원문 그대로 보존하며, 단순히 QA 점수를 맞추기 위해 품명을 임의 교정하지 않습니다.

- HS2: 빠른 거시 탐색
- HS4: 산업 분석
- HS6: 국제 비교 가능한 상품 분석
- HS8: 한국 세부 상품 분석
- HSK10: 공급망/의존도 초정밀 분석
- Parquet을 기본 배포 형식으로 사용
- DuckDB 등 convenience view는 추후 추가 가능하지만 release canonical은 Parquet 유지
