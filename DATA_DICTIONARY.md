# Data dictionary

This dictionary documents the Kaggle-facing release files. One file represents one analytical grain to prevent accidental double counting across HS hierarchy levels.

## `trade_hs10_monthly.parquet`

Grain: `month × country_code × hs10`

| Column | Type | Description |
|---|---|---|
| `month` | string | Trade month, `YYYYMM`. |
| `country_code` | string | Korea Customs partner country/territory code. |
| `hs10` | string | Exact numeric 10-digit Korean HSK source code. |
| `hs8` | string | First 8 digits of HSK10; Korean national-detail prefix. |
| `hs6` | string | First 6 digits; international HS subheading. |
| `hs4` | string | First 4 digits; international HS heading. |
| `hs2` | string | First 2 digits; international HS chapter. |
| `export_usd` | int64 | Export value in USD, FOB basis. |
| `export_weight_kg` | int64 | Reported export net weight in kg. Rare negative source values are preserved. |
| `import_usd` | int64 | Import value in USD, CIF/customs-value basis. |
| `import_weight_kg` | int64 | Reported import net weight in kg. Rare negative source values are preserved. |
| `trade_balance_usd` | int64 | `export_usd - import_usd`. |
| `hs_revision` | string/null | `HSK-YYYY` if the official annual CLIP reference contains this code; otherwise null. |

## Derived HS8 / HS6 / HS4 / HS2 files

Grain: `month × country_code × hsN` where N is 8, 6, 4, or 2.

All derived files contain the hierarchy keys applicable to their level plus the five main measures. They additionally contain:

| Column | Type | Description |
|---|---|---|
| `residual_export_usd` | int64 | Export USD contributed by safely mappable non-HSK10 source rows. |
| `residual_export_weight_kg` | int64 | Export kg contributed by safely mappable non-HSK10 rows. |
| `residual_import_usd` | int64 | Import USD contributed by safely mappable non-HSK10 rows. |
| `residual_import_weight_kg` | int64 | Import kg contributed by safely mappable non-HSK10 rows. |
| `residual_trade_balance_usd` | int64 | Trade-balance contribution of mapped residual rows. |
| `source_row_count` | int64 | Number of source fact rows contributing to the aggregate. |
| `exception_row_count` | int64 | Number of non-HSK10 source exceptions mapped to the aggregate. |
| `has_residual` | bool | Whether any source exception contributes to the aggregate. |

Residual mapping is conservative: a 6-digit source row can contribute to HS6/HS4/HS2, but never to a specific HS8 child. No proportional allocation or zero-padding is performed.

## `hsk_code_reference.parquet`

Grain: `reference_year × hs10`

| Column | Description |
|---|---|
| `reference_year` | Annual KCS CLIP edition year. |
| `hs_revision` | `HSK-YYYY` annual edition label. |
| `valid_from`, `valid_to` | Annual-reference validity fields; do not interpret as inferred sub-annual legal amendment boundaries. |
| `clip_sct_year`, `clip_hstd_year` | Official CLIP version fields returned by the source. |
| `hs10`, `hs8`, `hs6`, `hs4`, `hs2` | HSK hierarchy codes. |
| `name_ko` | Official Korean item name. |
| `name_en` | Official English item name. |
| `source`, `source_url` | Provenance fields. |

## `country_reference.csv`

| Column | Description |
|---|---|
| `country_code` | KCS collection code. |
| `country_name_ko` | Official Korean KCS name. |
| `country_name_en` | UN M49 English name on exact current alpha-2 match only. |
| `un_m49` | UN M49 numeric code when exactly matched. |
| `iso_alpha3` | ISO alpha-3 on exact UN match. |
| `un_match_status` | Exact-match status. |
| `kcs_source_version` | KCS lookup workbook version. |
| `kcs_source_row` | Original workbook row for reproducibility. |

## Audit files

- `source_code_exceptions.parquet`: source rows whose HS code is not exactly 10 numeric digits. These rows are not discarded or padded.
- `source_weight_warnings.parquet`: source rows with negative reported weight. Monetary amounts and balances remain valid; weights are preserved exactly.
- `hsk_reference_gaps.csv`: `(reference_year, hs10)` combinations present in trade data but absent from the same-year annual CLIP code table.
- `coverage_report.csv`: release QA metrics.
- `release_manifest.json`: row counts, file sizes, hashes, date coverage, and reconciliation summary.
