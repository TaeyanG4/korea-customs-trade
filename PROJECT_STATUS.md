# Project status

Last updated: 2026-09-08

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

## Pending live work

The local `KCS_SERVICE_KEY` has been configured, but the current data.go.kr daily allowance is exhausted. Live calls should resume after quota availability returns or after an approved traffic increase.

1. Apply for an operating account / increased traffic allowance if available for the current usage application.
2. When quota is available, run US x 2025 with `hsSgn` omitted.
3. Inspect the generated pilot report and raw response.
4. If the root hypothesis passes, run the 5-country x 4-year matrix.
5. Re-estimate total dataset size and worst-case request count from observed split rates.
6. Only then proceed to the production collector and normalization pipeline.
