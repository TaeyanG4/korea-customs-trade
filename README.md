# South Korea Customs Trade 2012–2026 — 10-Digit Product Level

![Korea Customs Trade Kaggle banner](assets/korea_customs_trade_kaggle_banner.jpg)

[한국어 README](README.ko.md)

This repository builds a reproducible Kaggle data product from official Korea Customs Service public data. The intended source-of-truth grain is:

`month × partner_country × HSK10`

The final dataset will preserve full Korean **10-digit HSK** detail and derive `hs6`, `hs4`, and `hs2` locally from the HSK10 prefix instead of collecting those aggregation levels separately.

## Current phase

The project is in the **API pilot** phase. Before any full backfill, it tests the most important collection assumption:

> When `cntyCd` and a period are supplied but `hsSgn` is omitted, does the Korea Customs item-by-country API return the full monthly HSK10 trade rows for that country?

The first live test is **US × 2025**. The planned pilot matrix is:

- Countries: `US`, `CN`, `JP`, `VN`, `DE`
- Years: `2012`, `2017`, `2022`, `2025`

No full crawl should begin until this pilot passes.

### Roadmap progress

Current stage: **8/12 — normalization and Parquet output**. Stages 1–7 are complete. The production collector now schedules all 269 official KCS codes, computes the latest stable month conservatively, reuses successful checkpoints, records run-level manifests, stops on daily quota exhaustion, retries per-second rate limits, and supports both historical backfill and 13-month revision refreshes.

The matrix also exposed a small but important upstream data-quality exception: 5 of 1,379,734 fact rows were not 10-digit HSK (four 6-digit rows and one 9-digit row). These rows were reproduced by targeted API checks, so they are not parser errors. They are preserved in raw XML and quarantined to `non_hs10_rows.csv`; the canonical HSK10 fact table will never pad or guess them into a 10-digit code.

The official KCS lookup workbook currently yields **269 unique country codes**. All 269 were accepted by a live 2025-01 API validation; 236 had trade rows that month and 33 returned no trade rows. The all-code January census contained **128,207 fact rows**, all numeric HSK10. This resets the full-history planning band to roughly **22–35 million rows** rather than the earlier major-country-biased estimate. The production root-request count is **4,035** (269 codes × 15 calendar years) before adaptive splits. Parquet size will be measured in stage 8 rather than guessed.

Country-code authority policy:

- `country_code` and `country_name_ko`: Korea Customs Service `관세청조회코드_v1.3.xlsx`
- English/M49/alpha3 enrichment: exact alpha-2 matches from UN Statistics Division M49 only
- unmatched KCS codes are retained with blank English/UN fields; they are never dropped or guessed

## Production collector

Dry-run the full plan before any large collection:

```powershell
python .\collector.py --dry-run backfill
```

On 2026-09-08 this resolves to `201201–202607`, 269 country codes, 15 calendar-year windows and **4,035 root requests**. The current stable-month rule uses the prior month only after the 15th; before then it uses two months back.

The full backfill command is available but is intentionally reserved for stage 9, after normalization is proven:

```powershell
.\run_backfill.ps1
```

Monthly revision refresh mode refetches the latest stable month plus the previous 12 months:

```powershell
.\run_refresh.ps1
```

For smoke tests, use `--countries`, `--max-roots`, and `--dry-run`. A production run manifest is written under `data/audits/runs/` and never contains the service key.

## Official API

- Korea Customs Service item-by-country import/export performance (GW)
- Endpoint: `https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList`
- Core parameters: `serviceKey`, `strtYymm`, `endYymm`, `cntyCd`
- `hsSgn` is intentionally omitted by the pilot.

## What the pilot records

Every request preserves the raw response and records enough metadata to support audit and resume:

- HTTP status and API result code/message
- exact response bytes and SHA-256
- gzip-compressed raw XML
- item and fact-row counts
- observed HS-code length distribution
- numeric 10-digit HSK compliance
- requested-month coverage
- duplicate `(month, country, hs10)` keys
- zero-trade rows
- negative amount/weight rows
- `trade_balance == export - import` reconciliation
- country-code mismatches
- observed Korean HSK-name variants
- elapsed time and retry count

The data.go.kr service key is never written to manifests.

## Adaptive request splitting

The logical collection unit is `country × year`. Retryable transport failures automatically split:

```text
country × year
  -> country × quarter
      -> country × month
```

Authentication, parameter, and API-level errors are not hidden by splitting.

## API quota strategy

The official data.go.kr page currently lists **10,000 requests/day for a development account**. The same page states that an **operating account can request increased traffic after registering a usage case**, and this Korea Customs API requires review at the operating stage.

For this project, quota should be managed conservatively:

- Prefer one `country × year` request. If that succeeds consistently, roughly 240 countries × 15 years is only about 3,600 root requests.
- Do not pre-split successful requests into quarters or months; adaptive splitting is only a fallback for oversized/time-out responses.
- If data.go.kr returns gateway reason code `22` (`LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR`), the collector stops the run immediately instead of wasting more calls. Successful manifests remain resumable.
- Apply for an operating account / traffic increase before the production backfill if pilot measurements show that adaptive splitting could push the run above the daily allowance.
- Do not use multiple personal accounts or keys to bypass platform limits.

The public file dataset named `관세청_월별_품목별_국가별 수출입실적` is useful as an auxiliary official reference, but its published coverage is HS4 for 2021–2023, so it is not a substitute for this project's HSK10 source of truth.

## Setup on Windows PowerShell

```powershell
cd H:\dev\kaggle-data\korea-customs-trade
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:KCS_SERVICE_KEY='YOUR_DATA_GO_KR_SERVICE_KEY'
```

Alternatively, create a local `.env` file in the project root:

```text
KCS_SERVICE_KEY=YOUR_DATA_GO_KR_SERVICE_KEY
```

The collector loads `.env` automatically when the process environment does not already contain the key. `.env` is excluded from Git.

Run the first pilot:

```powershell
.\run_us_2025.ps1
```

Only after reviewing the pilot report, run the matrix:

```powershell
.\run_matrix.ps1
```

## Setup on Linux / macOS

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export KCS_SERVICE_KEY='YOUR_DATA_GO_KR_SERVICE_KEY'
./run_us_2025.sh
```

## Output layout

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

Raw and generated data are excluded from Git by default. GitHub is used to back up code, configuration templates, documentation, and reproducible pipeline logic—not service keys or bulky raw responses.

## Tests

```powershell
pytest -q
```

## Pilot release gate

A logical country-year receives `PASS` only when all effective leaf requests succeed, at least one fact row is returned, every fact row has a numeric 10-digit HS code, all requested months are represented, and there are no duplicate `(month, country, hs10)` keys.

A pilot `PASS` verifies observed API behavior for the tested request. It does **not** prove historical HSK-code completeness. Public release will still require reconciliation against independent official aggregates and revision-aware HSK codebooks.

## Planned canonical fact schema

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

HSK names and country names should live in dimensions rather than repeat across the fact table wherever possible.

## Dataset positioning

Target Kaggle dataset:

**South Korea Customs Trade 2012–2026 — 10-Digit Product Level**

Positioning statement:

> South Korea's monthly customs trade at the full 10-digit HSK product level, across 200+ partner economies, with HS6/HS4/HS2 mappings and long-term history.
