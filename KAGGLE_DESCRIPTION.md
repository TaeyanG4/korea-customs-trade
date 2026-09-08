# South Korea Customs Trade 2012–2026 — 10-Digit Product Level

Monthly South Korean customs trade with **269 partner country/territory codes** and full **10-digit Korean HSK product detail**, built reproducibly from official Korea Customs Service public data.

## Why this dataset

Most trade datasets stop at HS2, HS4, or HS6. This release keeps the full Korean HSK10 detail while also providing ready-to-use HS8, HS6, HS4, and HS2 monthly tables so you can choose the right grain without re-aggregating tens of millions of rows yourself.

The data covers **2012-01 through 2026-07** and is designed for trade-network analysis, supply-chain dependency research, industrial structure, product diversification, bilateral trade analysis, and forecasting.

## What is included

- `trade_hs10_monthly.parquet` — strict 10-digit HSK canonical facts
- `trade_hs8_monthly.parquet` — Korean national-detail prefix aggregate
- `trade_hs6_monthly.parquet` — recommended international-comparison table
- `trade_hs4_monthly.parquet` — heading-level industry view
- `trade_hs2_monthly.parquet` — chapter-level macro view
- `trade_hs6_202607_sample.csv` — latest-month convenience sample for quick preview
- annual HSK Korean/English reference, country reference, source-exception audits, release manifest, coverage report, data dictionary, methodology, and provenance

## Quality and source fidelity

The collection completed **4,035 / 4,035 scheduled country-year roots** with zero unresolved API failures. Stage-11 normalization reconciled **22,351,483 source fact rows** into **22,351,430 strict HSK10 rows + 53 non-HSK10 source exceptions**. Duplicate canonical keys and partition mismatches are zero.

Rare source anomalies are **not silently cleaned away**. Non-HSK10 rows are quarantined instead of padded into invented HSK10 codes. Nineteen source rows with negative reported weight are preserved exactly and exposed as warnings. HSK10 trade facts missing from the same-year annual CLIP reference remain in the dataset with `hs_revision = null` and are audited rather than dropped.

Exports are reported in USD on an **FOB** basis, imports in USD on a **CIF/customs-value** basis, and weights are net kilograms as published by Korea Customs.

## Recommended starting point

For most cross-country product analysis, start with **HS6**. Use **HSK10** when you need Korean product-level detail or supply-chain precision.

```python
import pandas as pd

df = pd.read_parquet('/kaggle/input/south-korea-customs-trade-hsk10/trade_hs6_monthly.parquet')
semiconductors = df[df['hs6'].str.startswith('8542')]
```

## Updates

The intended update frequency is **monthly**. Refreshes re-fetch the latest stable month plus the preceding 12 months so customs revisions, withdrawals, and corrections can replace older values rather than accumulating stale append-only rows.

## 한국어 요약

관세청 공식 공공데이터를 기반으로 구축한 월별 국가 × 품목 수출입 데이터셋입니다. 2012년 1월부터 2026년 7월까지 269개 관세청 국가코드와 한국 HSK 10자리 품목을 Source of Truth로 보존하고, 분석 편의를 위해 HS8/HS6/HS4/HS2 집계 파일도 제공합니다. 원천의 예외값은 임의 수정하지 않고 별도 audit로 공개합니다.
