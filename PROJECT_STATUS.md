# Project status

Last updated: 2026-09-09

## Roadmap progress

Current stage: **12/12 — public Kaggle release live; Usability 10.00 achieved**

Release objective: **Kaggle Usability 10.00 + Dataset medal**. Avoid over-cleaning; preserve official source truth and prioritize analyst usability, documentation, reproducibility, and encoding-safe release files.

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
- Production collector implemented with official 269-code scheduling, stable-month logic, annual windows, run manifests, checkpoint accounting, quota stop, per-second rate-limit retry, dry-run/subset smoke-test controls, and refresh mode.
- Default backfill plan on 2026-09-08 resolves to 2012-01 through 2026-07: 269 countries × 15 calendar-year windows = 4,035 roots.
- Refresh mode refetches the latest stable month plus the preceding 12 months (13 inclusive months) and currently resolves to 2025-07 through 2026-07.
- Production smoke tests passed both checkpoint reuse (US 2025) and a new live annual request (AD 2025, 101 rows).
- Revision-safe source selection implemented: each `(country, month)` uses exactly one latest successful request manifest, preventing duplicate normalized facts when refresh windows overlap historical backfill windows.
- Strict HSK10 normalization now uses the canonical 13-column schema including `hs8`; `hs_revision` is populated from the official annual CLIP HSK reference when `(year, hs10)` exists and otherwise remains null with an audit entry.
- Parquet layout uses `year=YYYY/mm=MM` partitions to avoid a Hive partition-name collision with the canonical `month=YYYYMM` column.
- Current real-data normalization sample: 1,756,794 canonical HSK10 rows, 5 non-HSK10 upstream anomalies quarantined, 48 monthly files, 0 duplicate keys, 0 partition mismatches, 0 fatal anomalies.
- Sample HSK10 Parquet size: 36,000,067 bytes (~20.5 bytes/input row), normalized in about 33 seconds.
- HS8/HS6/HS4/HS2 are derived locally from strict HSK10. Numeric non-HSK10 source residuals are included only at hierarchy levels that can be identified safely from the existing prefix; no padding or allocation is inferred.
- The older stage-8 sample measured HS6 1,091,103 rows / 21.84 MB; HS4 353,003 / 7.68 MB; HS2 39,934 / 1.06 MB. Stage 11 will replace these with full-history HS8/HS6/HS4/HS2 outputs and actual final sizes.
- Full historical backfill completed: 4,035/4,035 scheduled roots succeeded, 22,351,483 fact rows collected, 343 successful checkpoints reused, 0 unresolved failures.
- Durable analyst-facing data model is documented in `DATA_MODEL.md` / `DATA_MODEL.ko.md`: separate HS2/HS4/HS6/HS8/HSK10 files, strict HSK10 canonical grain, non-HSK10 quarantine, and residual-aware upper-level aggregation without guessing.
- Official revision-reference source selected: Korea Customs Service CLIP annual Korean tariff tables, available across the project period.
- `hsk_reference.py` implements cached/resumable CLIP retrieval using one request per HS chapter, strict HSK10 parsing, Korean/English names, HS8/HS6/HS4/HS2 prefixes, annual `HSK-YYYY` editions, combined Parquet output, duplicate-label audits, and adjacent-year revision-transition review.
- Stage 10 full collection completed for 2012–2026. The combined official HSK reference contains 178,911 `(reference_year, hs10)` rows with 0 missing Korean names, 0 missing English names, 0 invalid HSK10 values, 0 duplicate annual keys, and 0 prefix mismatches.
- Three same-code source label variants were observed: two compatible 2012 wording expansions and one 2022 revision-boundary conflict. The 2022 conflict was resolved automatically against the adjacent 2021/2023 annual editions; unresolved duplicate-label reviews: 0.
- Full test suite currently passes 47 tests, including regression coverage for the public HSK10 supply-chain Notebook and HS6 machine-learning forecast Notebook.
- Stage 11 code now targets annual HSK revision linkage, HS8/HS6/HS4/HS2 residual-aware analyst aggregates, and an automated Korean-text/UTF-8 release gate. Canonical source facts are not dropped merely because an HSK10 is absent from the annual CLIP reference; such rows keep a null revision and are audited.
- Stage 11 dry-run confirms complete source selection: 4,035 successful source manifests, 47,075/47,075 country-month assignments, 2012-01 through 2026-07, and 0 overlap assignments.
- A real US x 2025 stage-11 normalization smoke produced 77,606 canonical rows, 0 fatal anomalies, exact USD/trade-balance agreement with the response summary, and only 740 kg of accepted cumulative row-level weight rounding across 77,606 facts. Two January 2025 HSK10 codes are absent from the 2025 CLIP annual edition but exist through the 2024 edition; they remain canonical with null `hs_revision` and are audited rather than reassigned by inference.
- The first full stage-11 normalization pass exposed 19 upstream rows with negative reported weight (but non-negative trade amounts and valid balances). These are now treated as source warnings rather than dropped facts: negative weights remain signed in canonical data and are surfaced in the anomaly audit. Negative monetary amounts remain fatal.
- Stage 11 final release QA passes with `release_gate_pass=True`, 0 fatal sections, 22,351,430 strict HSK10 rows, 53 non-HSK10 source residual rows, and 19 preserved negative-weight warnings.
- Stage 12 Kaggle release package is built under `release/kaggle/`. The five analyst tables contain: HSK10 22,351,430 rows / 417,772,573 bytes; HS8 20,576,865 / 353,063,936; HS6 16,059,132 / 256,630,827; HS4 7,234,105 / 124,283,327; HS2 1,446,045 / 28,697,114.
- Kaggle-facing support files include the 178,911-row annual HSK reference, 269-row country reference, 53-row non-HSK10 exception table, 19-row negative-weight warning table, 925-row HSK-reference-gap audit, latest-month HS6 CSV sample, coverage report, data dictionary, methodology, sources, cover image, dataset metadata, and release manifest.
- All upload-facing text/CSV files decode strictly as UTF-8. Korean values in the HSK reference, HSK-reference-gap audit, source-code exceptions, and weight-warning table were rechecked at Unicode codepoint level and are intact; earlier mojibake-like terminal output was a console-rendering artifact, not file corruption.
- SHA-256 verification re-read every checksummed release artifact and matched the release manifest for all 15 recorded files.
- Stage 11 full rebuild completed and passed release QA: 22,351,430 strict HSK10 rows, 53 non-HSK10 source residual rows, 19 preserved negative-weight warning rows, 175 monthly partitions, 0 duplicate canonical keys, 0 partition mismatches, and `release_gate_pass=true` with 0 fatal sections.
- Full derived outputs completed for HS8/HS6/HS4/HS2 with 175 monthly partitions each and residual-aware total reconciliation.
- Stage 12 packaged one Parquet per analytical grain, a latest-month HS6 preview CSV, references/audits, a checksummed release manifest, Kaggle metadata, provenance, cover image, and usage documentation.
- Kaggle CLI is authenticated as `taeyangg4` with OAuth. Dataset Version 2 at `taeyangg4/south-korea-customs-trade-hsk10` is `Ready` and public.
- Guarded private-upload wrappers (`run_kaggle_private_upload.sh` / `.ps1`) now refuse upload unless release QA and the release manifest both pass and the metadata ID is exactly `taeyangg4/south-korea-customs-trade-hsk10`. They deliberately omit `--public`.
- A release-folder secret/path scan found no `serviceKey`, `KCS_SERVICE_KEY`, `.env`, or local project absolute path strings in upload-facing text/CSV/JSON files.
- Both Git Bash and PowerShell private-upload wrappers passed their `--preflight-only` / `-PreflightOnly` checks on 2026-09-09. The private-first validation completed successfully; Dataset Version 2 has a cover image, monthly update frequency, and seven live-valid discovery tags: `business`, `tabular`, `economics`, `time series analysis`, `government`, `asia`, and `international relations`.
- The Dataset and starter Notebook were subsequently published. Notebook Version 3 is public, completed successfully in Kaggle runtime, auto-discovers the mounted Dataset under `/kaggle/input`, and has no traceback or Korean glyph warning.
- A second public Notebook, `taeyangg4/korea-import-dependency-hsk10-supply-chain`, completed private-first validation and is public at Version 2. It reads only the latest 12 months of strict HSK10 rows, uses the current-geographic-partner analytical universe plus `TW`, and exposes Top-1/Top-3 partner shares, HHI, and concentration-weighted import exposure without presenting the result as a firm-level or causal supply-chain-risk measure.
- A third public Notebook, `taeyangg4/forecast-korea-imports-hs6-ml-vs-naive`, completed private-first validation and is public at Version 3. Product selection uses training-period data only; the latest 12 complete months (`202508`–`202607`) are held out chronologically. In the live Kaggle runtime, Gradient Boosting with Huber loss improves WAPE by **34.0% vs seasonal naive** and **8.4% vs lag-1 persistence**, with no traceback or user-code runtime warning, then refits on all available months for a `202608` one-step-ahead forecast.
- Kaggle Dataset API propagation now reports `kernelCount=3`, matching the starter, supply-chain, and ML forecast Notebooks; Dataset Usability remains `1.0` and visibility remains public.
- Public Dataset Usability is now **1.0 (10.00/10)**. Direct `DatasetDetailService/GetDatasetUsabilityRating` verification reports every component at `1`, including `fileDescriptionScore=1` and `columnDescriptionScore=1` alongside cover image, file format, license, overview, provenance, public Notebook, subtitle, tags, and update frequency.
- The release metadata contains descriptions for all 16 upload files and all 158 represented tabular columns. Kaggle CLI 2.2.4 and the official Kaggle MCP `update_dataset_metadata` path both accepted/read the metadata model but did not persist the Data Viewer descriptions through token-authenticated writes in this environment. The final successful persistence was performed once from the user's already authenticated Kaggle page using Kaggle's same-origin `UpdateDatabundleMetadataExternal` endpoint; all 16 file updates completed and the 158 column descriptions were preserved with the server-inferred column types.

## Live validation record

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

This full-code one-month census materially improves the scale estimate: holding January 2025 density constant across 180 months gives about 23.1 million rows. Because historical density and monthly seasonality vary, the production planning band is roughly **22–35 million rows**. At the measured ~32.1 gzip bytes per fact row, this suggests roughly **0.7–1.1 GB** of raw XML gzip for fact-row payload density alone; filesystem/XML overhead and retry/split artifacts justify retaining a more conservative local raw budget around **1–2 GB**.

The production root-request count is now based on the official code list: **269 country codes × 15 calendar years (2012–2026) = 4,035 root requests** before any adaptive splits. The representative matrix observed a 0% split rate.

Stage 8 is complete. The real-data sample measured roughly **20.5 HSK10 Parquet bytes per input row**. Applying the 22–35 million row planning band gives a provisional HSK10 Parquet range of roughly **451–717 MB**. Including measured HS6/HS4/HS2 derived outputs gives a combined partitioned Parquet estimate of roughly **0.83–1.33 GB** before release-packaging overhead.

Stages 9, 10, and 11 are complete. Stage 12 has completed package build, private-first validation, public Dataset publication, three public Notebook publications, Data Viewer file/column metadata persistence, and independent verification of **Usability 10.00**. The release-quality focus now shifts to sustained monthly refreshes, richer analytical/ML examples, and Dataset-medal discovery/engagement rather than further usability-score work.
