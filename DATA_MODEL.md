# Data model and Kaggle release architecture

[한국어](DATA_MODEL.ko.md)

This document is the durable design contract for the project. It should be treated as the source of truth when implementation details, chat context, or release packaging decisions are revisited later.

## 1. Collection principle

Collect the Korea Customs item-by-country API once at the most detailed available source level:

`country × calendar-year`, with `hsSgn` omitted.

Do **not** separately crawl HS2, HS4, HS6, HS8, and HSK10 endpoints/queries to build the main dataset. Lower levels are derived locally so that one revision-consistent source response drives every analytical view.

Raw XML is immutable evidence and is always retained locally with request manifests, hashes, and timestamps.

## 2. Canonical source grain

The canonical fact table is strictly:

`month × country_code × HSK10`

Only numeric 10-digit codes belong in the canonical HSK10 fact table. A shorter or otherwise non-HSK10 source code is never zero-padded, expanded, or guessed into a 10-digit code.

Canonical columns:

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

`hs8`, `hs6`, `hs4`, and `hs2` are prefix-derived from a valid HSK10 row. HS6 and above should not be interpreted as globally standardized beyond the international HS6 boundary; HS8/HSK10 are Korean national-detail prefixes/classifications.

## 3. Upstream mixed-granularity exceptions

The API has been empirically observed to return rare shorter codes alongside distinct HSK10 children in the same month. Examples include 6-digit and 9-digit rows. These are source records, not parser errors and not duplicate aggregate rows.

Policy:

- preserve the original row in raw XML;
- quarantine it in a structured exception table;
- never infer a missing HSK10;
- include its monetary/weight effect in reconciliation reporting;
- only roll it into an aggregate level when its observed prefix is sufficient to identify that level without guessing.

Target exception file:

`source_code_exceptions.parquet`

Suggested fields:

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

## 4. Analyst-facing levels

The Kaggle dataset should expose separate ready-to-use files rather than requiring users to merge mixed HS levels in one table:

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

The main usability rule is: **one file = one analytical grain**. A single long table containing HS2 + HS4 + HS6 + HS8 + HSK10 facts is not the primary release format because a naive sum would double-count the same trade at multiple hierarchy levels.

## 5. Residual-aware aggregation

Derived HS2/HS4/HS6/HS8 tables are not all equally complete when an upstream exception exists.

Example:

```text
761699        172 USD   # direct 6-digit residual from source
7616991000 165818 USD   # HSK10 child
7616999010   7075 USD   # HSK10 child
7616999090 1940201 USD  # HSK10 child
```

At HS6, the source residual can be assigned exactly to `761699`, so a complete HS6 total can be represented as:

`total = amount_from_hsk10_children + direct_source_residual`

For HS8, the 6-digit residual cannot be safely assigned to a particular HS8 child and must not be proportionally distributed or guessed.

Recommended aggregate measures where residuals exist:

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

The simple `export_usd` / `import_usd` columns should be the analyst-friendly total at levels where all source residuals can be assigned without inference. Coverage metadata must make any unallocatable residual explicit.

## 6. Level semantics

- **HS2**: broad international chapter-level analysis; source exceptions with at least two valid digits can be mapped safely.
- **HS4**: heading-level industry analysis; source exceptions with at least four valid digits can be mapped safely.
- **HS6**: international comparison level; a 6-digit direct source residual can be included exactly.
- **HS8**: Korean prefix-derived national detail; residuals shorter than 8 digits cannot be allocated to a child HS8 without guessing.
- **HSK10**: strict Korean 10-digit canonical fact; only exact numeric 10-digit source rows.

HS6 is the recommended default table for broad international analysis. HSK10 is the differentiating high-detail table for Korean product, supply-chain, and dependency research.

## 7. Revision policy

HSK definitions can change over time. The project must not assume that a numeric HSK10 has an identical meaning across all years.

Target HSK dimension:

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

Revision/version fields are populated only from official revision-aware sources. If an official historical definition is unavailable, retain observed API names and leave unsupported fields null rather than infer them.

## 8. Country dimension

Korea Customs Service is authoritative for the collection code and Korean name. UN M49 enrichment is used only on exact matches; unmatched KCS codes remain present without guessed English metadata.

```text
country_code
country_name_ko
country_name_en
alpha3
m49
```

## 9. Revision-safe refresh

The release is not append-only. Each monthly update should:

1. collect the latest stable month;
2. refetch the preceding 12 months;
3. select exactly one latest successful source for each `(country, month)`;
4. rebuild normalized facts for the affected period;
5. report rows added, removed, and changed plus value revisions.

## 10. Release quality gates

Before public release:

- zero missing scheduled requests;
- zero unresolved API failures;
- zero duplicate `(month, country_code, hs10)` canonical keys;
- zero invalid HSK10 rows in the canonical HSK10 table;
- zero month/partition mismatches;
- zero negative monetary-amount rows; negative source weights are preserved exactly, audited, and documented rather than silently clamped or dropped;
- zero unexplained trade-balance mismatches;
- source row counts reconcile with stored canonical + exception rows;
- exception/residual monetary impact is quantified;
- independent official totals are reconciled where possible;
- HSK revision coverage and unknown-code exceptions are reported.

## 11. Kaggle usability goal

The product goal is not merely to publish the largest Korean customs file. It is to make South Korean customs trade unusually easy to analyze:

The product target is **Kaggle Usability 10.00 plus a Dataset medal**, without over-cleaning official source data. We prioritize reproducible official sourcing, clear grains, ready-to-use Parquet, documentation, stable updates, and auditable quality over cosmetic rewriting.

Korean-text integrity is a release blocker. Upload-facing CSV/Markdown must decode strictly as UTF-8, and Korean reference fields must not contain replacement characters, invalid controls, or decoding damage that removes Hangul. Source exceptions are preserved faithfully rather than rewritten merely to satisfy QA.

- HS2 for quick macro exploration;
- HS4 for industry analysis;
- HS6 for internationally comparable product analysis;
- HS8 for Korean national-detail work;
- HSK10 for high-resolution supply-chain research;
- Parquet as the primary distribution format;
- optional DuckDB/convenience views may be added later, but Parquet remains canonical for release.
