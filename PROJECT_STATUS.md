# Project status

Last updated: 2026-09-08

## Roadmap progress

Current stage: **7/12 — design and implement the production collector**

1. Project status / README refresh for the active API key
2. US x 2025 full-year pilot with `hsSgn` omitted
3. Inspect pilot results and validate the central HSK10 hypothesis
4. Run the 5-country x 4-year representative pilot matrix
5. Re-estimate total row count, storage, runtime, and request volume
6. Acquire and validate the official country-code reference
7. Design and implement the production collector
8. Implement normalization and Parquet output
9. Run the full historical backfill
10. Build the revision-aware HSK dimension
11. Run reconciliation and release QA
12. Build and publish the Kaggle release package

## Implemented

- Official Korea Customs item-by-country endpoint configured.
- `hsSgn` intentionally omitted for the central pilot hypothesis.
- First probe command: US x 2025.
- Planned pilot matrix: US/CN/JP/VN/DE x 2012/2017/2022/2025.
- Country-year request with retry and adaptive year -> quarter -> month split.
- Raw XML retained as gzip.
- SHA-256 and response-byte count.
- Per-request JSON manifest without the service key.
- Checkpoint/resume using successful manifests.
- Streaming XML parse.
- HSK10 length/numeric checks.
- Month coverage checks.
- Duplicate `(month, country, hs10)` checks.
- Zero-trade row count.
- Negative amount/weight checks.
- Trade-balance reconciliation.
- Country-code mismatch checks.
- Observed Korean HS-name variation audit.
- Logical country-year PASS/FAIL even when adaptive split is used.
- Unit tests for parsing, validation, retry, secret exclusion, and split aggregation.
- data.go.kr gateway quota code 22 detection; a quota-exhausted run stops immediately instead of continuing across the matrix.
- Official quota strategy documented: development 10,000 requests/day; operating account can request more traffic after registering a usage case.
- Local `.env` auto-loading for `KCS_SERVICE_KEY`; process-level environment variables still take precedence.
- Service keys are redacted from exception URLs before manifests are written.
- Representative matrix completed: 20/20 country-year requests succeeded as annual requests, with 0 retries and 0 adaptive splits.
- Rare mixed-granularity API rows are quarantined to `non_hs10_rows.csv`; they are never zero-padded or guessed into HSK10.
- Scale-calibration sample added for 20 additional countries in 2025.
- Official KCS `관세청조회코드_v1.3.xlsx` is downloaded reproducibly and its `국가코드` sheet builds `country_reference.csv`.
- KCS country code / Korean name is authoritative; UN M49 enriches exact current alpha-2 matches only.
- Country reference contains 269 unique KCS codes; 248 exact UN M49 matches and 21 unmatched KCS codes retained without inference.
- All 269 KCS country codes were accepted by the live API for 2025-01 with `resultCode=00`.

## Pending live work

The operating/traffic increase application has been approved and the project-local `.env` contains the active key. A live probe returns HTTP 200 / `resultCode=00`.

Stages 2 and 3 are complete. US x 2025 succeeded as a single annual request with `hsSgn` omitted:

- 77,606 fact rows, all numeric 10-digit HSK
- 12/12 requested months present
- 0 duplicate `(month, country, hs10)` rows
- 0 country mismatches
- 0 negative amount/weight rows
- 0 trade-balance mismatches
- 30 zero-trade rows
- 21,279,226 uncompressed XML bytes; 2,524,312 gzip bytes
- 6.016 seconds, 0 retries, no adaptive split
- 8,861 unique HSK10 codes observed across the year

The central `hsSgn`-omission hypothesis passes cleanly for US x 2025. The 5-country x 4-year matrix also completed successfully at the request level, but exposed 5 raw mixed-granularity records among 1,379,734 fact rows: four 6-digit rows and one 9-digit row. Explicit prefix re-queries reproduced these records, proving they are upstream API/data exceptions rather than parser errors. Their observed impact in the matrix was USD 321 of exports and USD 0 of imports. Canonical HSK10 output will therefore remain strict numeric 10-digit data, while all non-HSK10 rows are preserved in raw XML and a separate anomaly audit.

Stage 5 scale calibration is complete enough for planning. The original 5-country pilot is biased toward major trading partners, so 20 additional 2025 country-years were sampled across medium and small partners. Observed annual row averages were approximately:

- major sample: 70,923 rows/country-year
- medium sample: 32,617 rows/country-year
- small sample: 5,080 rows/country-year

Measured transport/storage characteristics across the representative matrix were about 275 uncompressed XML bytes per fact row, 32.1 gzip bytes per fact row, and an 11.7% gzip/raw ratio. Annual requests averaged about 5.5 seconds for the major-partner matrix and remained split-free.

Stage 6 replaces the provisional country-count assumption. The official KCS lookup workbook contains 269 unique country codes. A live one-month validation accepted 269/269 codes; 236 had fact rows in 2025-01 and 33 had zero trade rows for that month. Across all 269 codes, 2025-01 contained 128,207 fact rows and all were numeric HSK10 with no returned-country mismatch.

This full-code one-month census materially improves the scale estimate: holding January 2025 density constant across 180 months gives about 23.1 million rows. Because historical density and monthly seasonality vary, the production planning band is reset to roughly **22–35 million rows**, consistent with the original project estimate. At the measured ~32.1 gzip bytes per fact row, this suggests roughly **0.7–1.1 GB** of raw XML gzip for fact-row payload density alone; filesystem/XML overhead and retry/split artifacts justify retaining a more conservative local raw budget around **1–2 GB**. Exact Parquet size remains unmeasured until stage 8.

The production root-request count is now based on the official code list: **269 country codes × 15 calendar years (2012–2026) = 4,035 root requests** before any adaptive splits. The representative matrix observed a 0% split rate.

Next action: turn the proven pilot logic into a production collector driven by the official 269-code reference, with release-safe checkpoints, resumability, quota handling, and explicit stable-month boundaries.
