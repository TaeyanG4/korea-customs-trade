# Methodology

## 1. Official collection source

The primary fact source is the Korea Customs Service **item-by-country import/export performance (GW)** API on the Korea Public Data Portal. Collection requests specify partner country and time period while intentionally omitting `hsSgn`, allowing the API to return its detailed product rows.

The production logical root is `country × calendar-year`. Retryable transport/size failures may adaptively split year → quarter → month. Authentication, parameter, and explicit API errors are not hidden by splitting.

## 2. Raw evidence and reproducibility

Every successful response is retained locally as gzip-compressed XML with a request manifest containing request parameters, timestamps, response size, SHA-256, API status, retry information, and row counts. Service keys are never written to manifests.

## 3. Revision-safe source selection

Monthly customs data can be revised. Overlapping refresh requests therefore do not append blindly. For every `(country, month)`, normalization selects exactly one latest successful source manifest. A later corrected source can add, change, or remove rows from the rebuilt dataset.

## 4. Canonical HSK10 normalization

The canonical fact grain is `month × country_code × hs10` and accepts only exact numeric 10-digit source codes. `hs8`, `hs6`, `hs4`, and `hs2` are prefix-derived locally.

Shorter source codes are preserved as exceptions. They are never padded with zeros or guessed into a child HSK10 code.

## 5. Residual-aware upper-level tables

HS8/HS6/HS4/HS2 are derived from the canonical HSK10 data. A non-HSK10 source exception is added only to a hierarchy level that can be identified from its observed digits without inference. For example, a 6-digit exception can be included exactly in HS6, HS4, and HS2 totals but cannot be assigned to one of several possible HS8 children.

The derived tables expose `residual_*`, `exception_row_count`, and `has_residual` so analysts can distinguish canonical HSK10 contributions from mapped source residuals.

## 6. HSK revision reference

Historical HSK labels come from the official Korea Customs Service CLIP annual Korean tariff tables for 2012–2026. `HSK-YYYY` means the annual CLIP edition. The project does not invent unsupported sub-annual amendment boundaries.

If a trade HSK10 is absent from the same-year annual reference, the trade fact remains canonical with `hs_revision = null` and appears in the reference-gap audit.

## 7. Reconciliation and source anomalies

Where an API response provides an overall summary row, detailed fact totals are reconciled against it. USD values and trade balance must match exactly. Row-level weights are published as integer kg, so a conservative cumulative rounding tolerance is allowed and audited.

Negative monetary amounts are a release-blocking anomaly. Rare negative source weights are not silently corrected: they remain signed in the canonical and derived data and are listed in `source_weight_warnings.parquet`.

## 8. Release QA

The Stage-11 release gate checks complete source coverage, zero unresolved API failures, strict HSK10 structure, duplicate keys, partition consistency, source-row reconciliation, summary reconciliation, HSK reference integrity, derived-level total reconciliation, and UTF-8/Korean text integrity.

## 9. Monthly update strategy

Each update should collect the latest stable month and re-fetch the preceding 12 months. The affected normalized and derived ranges are rebuilt using latest-success source selection, and release differences should be reported rather than treated as append-only history.
