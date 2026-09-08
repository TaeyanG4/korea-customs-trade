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

## Pending live work

The live API probe still requires a valid local `KCS_SERVICE_KEY` and network access.

1. Run US x 2025 with `hsSgn` omitted.
2. Inspect the generated pilot report and raw response.
3. If the root hypothesis passes, run the 5-country x 4-year matrix.
4. Re-estimate total dataset size from observed response sizes and row counts.
5. Only then proceed to the production collector and normalization pipeline.
