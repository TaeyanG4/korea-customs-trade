# Project status

Last updated: 2026-09-08

## Roadmap progress

Current stage: **1/12 — project status and documentation refresh**

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

## Pending live work

The operating/traffic increase application has been approved and the service key changed as part of that approval. The project-local `.env` has been updated with the active key. A live probe on 2026-09-08 returned HTTP 200 / `resultCode=00`, confirming that the API is currently callable.

Next action: run the full US x 2025 request with `hsSgn` omitted, then inspect the generated raw XML and pilot report before allowing the representative matrix or any production crawl.
