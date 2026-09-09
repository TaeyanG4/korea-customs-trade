from __future__ import annotations

import json
from pathlib import Path

import nbformat as nbf


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kaggle_notebooks" / "import_dependency_hsk10"
NOTEBOOK = OUT / "korea_import_dependency_hsk10.ipynb"
METADATA = OUT / "kernel-metadata.json"


def md(text: str):
    return nbf.v4.new_markdown_cell(text.strip() + "\n")


def code(text: str):
    return nbf.v4.new_code_cell(text.strip() + "\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    cells = [
        md(
            """
# Korea Import Dependency - HSK10 Supply Chain Concentration

Which Korean import products are economically large **and** concentrated in only a few partner countries?

This notebook uses the most detailed **10-digit Korean HSK** table from the South Korea Customs Trade Dataset and turns the latest 12 months into a compact supply-chain concentration screen.

We calculate four transparent metrics for every imported HSK10 product:

- **Top-1 partner share** - share of imports coming from the largest customs partner.
- **Top-3 partner share** - combined share of the three largest partners.
- **HHI** - sum of squared partner shares; higher values mean a more concentrated partner mix.
- **Concentration-weighted import exposure** - 12-month import value multiplied by HHI. This is only a ranking aid, **not** an estimate of economic loss.

The analysis is a **customs import-partner concentration proxy**. It does not identify firm-level suppliers, inventories, contractual substitutability, or ultimate country of origin.

**Source:** Korea Customs Service public data.
**Analytical grain:** `month x partner country x HSK10`.
"""
        ),
        code(
            r'''
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import matplotlib.pyplot as plt

pd.set_option("display.max_columns", 30)
pd.set_option("display.float_format", lambda x: f"{x:,.3f}")

DATA = None
kaggle_input = Path("/kaggle/input")
if kaggle_input.exists():
    matches = list(kaggle_input.rglob("trade_hs10_monthly.parquet"))
    for match in matches:
        candidate = match.parent
        required = [
            "country_reference.csv",
            "hsk_code_reference.parquet",
            "release_manifest.json",
        ]
        if all((candidate / name).exists() for name in required):
            DATA = candidate
            break

if DATA is None:
    local_candidates = [
        Path.cwd() / "release" / "kaggle",
        Path.cwd().parent.parent / "release" / "kaggle",
    ]
    DATA = next((path for path in local_candidates if path.exists()), None)

if DATA is None:
    mounted = [str(path) for path in kaggle_input.iterdir()] if kaggle_input.exists() else []
    raise FileNotFoundError(f"Could not locate the Dataset files. Mounted inputs: {mounted}")

print("Data path:", DATA)
print("Dataset files:", len(list(DATA.iterdir())))
'''
        ),
        md(
            """
## 1. Use the latest 12 complete months

The release manifest tells us the latest stable month. We derive a rolling 12-month window from that value instead of hard-coding a date, so the notebook can survive future monthly Dataset refreshes.

For partner analysis we use **current UN geographic matches plus `TW`**, then exclude `KR`. The KCS country-code reference also contains historical, special, and aggregate codes; including those would distort concentration metrics.
"""
        ),
        code(
            r'''
manifest = json.loads((DATA / "release_manifest.json").read_text(encoding="utf-8"))
end_month = manifest["coverage"]["end_month"]
end_period = pd.Period(end_month, freq="M")
start_month = (end_period - 11).strftime("%Y%m")

countries = pd.read_csv(
    DATA / "country_reference.csv",
    dtype={"country_code": "string", "un_m49": "string", "iso_alpha3": "string"},
)

geo_codes = set(
    countries.loc[countries["un_match_status"].eq("matched_current_un"), "country_code"]
    .dropna()
    .astype(str)
)
geo_codes.add("TW")
geo_codes.discard("KR")

partner_names = countries[["country_code", "country_name_en"]].copy()
partner_names["partner_name"] = (
    partner_names["country_name_en"].fillna("").astype(str).str.strip()
)
missing_partner_name = partner_names["partner_name"].eq("")
partner_names.loc[missing_partner_name, "partner_name"] = partner_names.loc[
    missing_partner_name, "country_code"
]

print(f"Analysis window: {start_month} -> {end_month}")
print(f"Geographic partner codes used: {len(geo_codes):,}")
'''
        ),
        code(
            r'''
hsk10_ds = ds.dataset(DATA / "trade_hs10_monthly.parquet", format="parquet")

filter_expr = (
    (ds.field("month") >= start_month)
    & (ds.field("month") <= end_month)
    & ds.field("country_code").isin(sorted(geo_codes))
    & (ds.field("import_usd") > 0)
)

recent = hsk10_ds.to_table(
    filter=filter_expr,
    columns=["month", "country_code", "hs10", "hs6", "import_usd"],
).to_pandas()

print(f"Positive-import HSK10 rows: {len(recent):,}")
print(f"Distinct HSK10 products: {recent['hs10'].nunique():,}")
print(f"Partner codes represented: {recent['country_code'].nunique():,}")
print(f"Imports in analytical partner universe: ${recent['import_usd'].sum() / 1e9:,.1f}B")
recent.head()
'''
        ),
        md(
            """
## 2. Build transparent concentration metrics

For product `p` and partner `c`, let `s(p,c)` be that partner's share of the product's 12-month imports.

`HHI(p) = sum_c s(p,c)^2`

An HHI near 1 means almost all imports come from one partner; a lower HHI means the partner mix is more diversified. We keep the raw HHI and partner shares visible rather than hiding them behind a proprietary score.

To avoid tiny specialty products dominating the headline ranking, the main comparison below focuses on HSK10 products with at least **$100M of imports during the 12-month window**.
"""
        ),
        code(
            r'''
product_partner = (
    recent.groupby(["hs10", "hs6", "country_code"], as_index=False)["import_usd"]
    .sum()
)

product_totals = (
    product_partner.groupby(["hs10", "hs6"], as_index=False)["import_usd"]
    .sum()
    .rename(columns={"import_usd": "import_usd_12m"})
)

shares = product_partner.merge(product_totals, on=["hs10", "hs6"], how="left")
shares["share"] = shares["import_usd"] / shares["import_usd_12m"]
shares = shares.sort_values(["hs10", "share"], ascending=[True, False]).copy()
shares["partner_rank"] = shares.groupby("hs10").cumcount() + 1

metrics = (
    shares.groupby(["hs10", "hs6"], as_index=False)
    .agg(
        import_usd_12m=("import_usd_12m", "first"),
        hhi=("share", lambda s: float((s * s).sum())),
        top1_share=("share", "max"),
        partner_count=("country_code", "nunique"),
    )
)

top3 = (
    shares.loc[shares["partner_rank"] <= 3]
    .groupby("hs10")["share"]
    .sum()
    .rename("top3_share")
)
top1 = shares.loc[shares["partner_rank"] == 1, ["hs10", "country_code"]].rename(
    columns={"country_code": "top_partner_code"}
)

metrics = metrics.merge(top3, on="hs10", how="left").merge(top1, on="hs10", how="left")

reference_year = int(end_month[:4])
hsk_ref = ds.dataset(DATA / "hsk_code_reference.parquet", format="parquet").to_table(
    filter=ds.field("reference_year") == reference_year,
    columns=["hs10", "name_en"],
).to_pandas()
hsk_ref = hsk_ref.drop_duplicates("hs10")

metrics = (
    metrics.merge(hsk_ref, on="hs10", how="left")
    .merge(
        partner_names[["country_code", "partner_name"]],
        left_on="top_partner_code",
        right_on="country_code",
        how="left",
    )
    .drop(columns="country_code")
)
metrics["name_en"] = metrics["name_en"].fillna("Reference name unavailable")
metrics["partner_name"] = metrics["partner_name"].fillna(metrics["top_partner_code"])
metrics["concentration_exposure_usd"] = metrics["import_usd_12m"] * metrics["hhi"]
metrics["import_usd_bn"] = metrics["import_usd_12m"] / 1e9
metrics["concentration_exposure_bn"] = metrics["concentration_exposure_usd"] / 1e9

MIN_IMPORT_USD = 100_000_000
material = metrics.loc[metrics["import_usd_12m"] >= MIN_IMPORT_USD].copy()

print(f"HSK10 products with >= $100M imports: {len(material):,}")
print(f"Products with Top-1 partner share >= 80%: {(material['top1_share'] >= 0.80).sum():,}")
print(f"Products with HHI >= 0.50: {(material['hhi'] >= 0.50).sum():,}")
print(
    "Imports represented by >=80% Top-1 products: "
    f"${material.loc[material['top1_share'] >= 0.80, 'import_usd_12m'].sum() / 1e9:,.1f}B"
)
'''
        ),
        md(
            """
## 3. The largest concentration-weighted exposures

The ranking below is intentionally value-aware. A tiny product with a 100% partner share is less systemically interesting than a multi-billion-dollar product with similarly high concentration.

`concentration-weighted exposure = 12-month import value x HHI`

Again, this is a **screening statistic**, not a forecast of losses or a causal risk model.
"""
        ),
        code(
            r'''
top15 = material.nlargest(15, "concentration_exposure_usd").copy()
top15["name_short"] = top15["name_en"].str.slice(0, 58)

display_cols = [
    "hs10", "name_short", "import_usd_bn", "hhi", "top1_share", "top3_share",
    "partner_count", "top_partner_code", "partner_name", "concentration_exposure_bn",
]
top15[display_cols]
'''
        ),
        code(
            r'''
plot_data = top15.sort_values("concentration_exposure_bn").copy()
plot_data["label"] = plot_data["hs10"] + " | " + plot_data["name_short"]

fig, ax = plt.subplots(figsize=(11, 8))
ax.barh(plot_data["label"], plot_data["concentration_exposure_bn"])
ax.set_title("Largest HSK10 concentration-weighted import exposures")
ax.set_xlabel("12-month imports x HHI (USD billions)")
ax.set_ylabel("")
plt.tight_layout()
plt.show()
'''
        ),
        md(
            """
## 4. Scale and concentration are different dimensions

The scatter plot separates the two. Products on the right have a concentrated partner mix; products high on the chart have large import values. The upper-right is the most natural area for deeper supply-chain research.
"""
        ),
        code(
            r'''
fig, ax = plt.subplots(figsize=(10, 6))
ax.scatter(material["hhi"], material["import_usd_bn"], alpha=0.35, s=20)
ax.set_yscale("log")
ax.set_xlabel("HHI of import-partner shares")
ax.set_ylabel("12-month imports (USD billions, log scale)")
ax.set_title("Import scale vs partner concentration - HSK10 products >= $100M")

for _, row in top15.head(8).iterrows():
    ax.annotate(
        row["hs10"],
        (row["hhi"], row["import_usd_bn"]),
        xytext=(4, 4),
        textcoords="offset points",
        fontsize=8,
    )

plt.tight_layout()
plt.show()
'''
        ),
        md(
            """
## 5. What do the top partner mixes actually look like?

A high HHI can arise from very different structures. The charts below show the top eight import partners for the three highest concentration-weighted exposures.

`TW` is shown as the KCS code because the project deliberately does not invent an English UN-M49 match where the official reference does not provide one.
"""
        ),
        code(
            r'''
top_codes = top15.head(3)["hs10"].tolist()

for code_value in top_codes:
    summary = metrics.loc[metrics["hs10"].eq(code_value)].iloc[0]
    detail = (
        shares.loc[shares["hs10"].eq(code_value)]
        .merge(
            partner_names[["country_code", "partner_name"]],
            on="country_code",
            how="left",
        )
        .head(8)
        .sort_values("share")
        .copy()
    )
    detail["share_pct"] = detail["share"] * 100

    print(
        f"{code_value} | {summary['name_en']} | "
        f"imports ${summary['import_usd_bn']:,.1f}B | HHI {summary['hhi']:.3f} | "
        f"Top-1 {summary['top1_share']:.1%}"
    )

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(detail["partner_name"], detail["share_pct"])
    ax.set_title(f"{code_value} - top import partners")
    ax.set_xlabel("Share of 12-month imports (%)")
    ax.set_ylabel("")
    plt.tight_layout()
    plt.show()
'''
        ),
        md(
            """
## 6. Reusable product lookup

The helper below lets you inspect any HSK10 code from the current 12-month window without rebuilding the metrics.
"""
        ),
        code(
            r'''
def dependency_snapshot(hs10_code: str, top_n: int = 10):
    row = metrics.loc[metrics["hs10"].eq(hs10_code)]
    if row.empty:
        raise KeyError(f"HSK10 {hs10_code} has no positive imports in this analysis window")

    summary = row.iloc[0]
    detail = (
        shares.loc[shares["hs10"].eq(hs10_code)]
        .merge(
            partner_names[["country_code", "partner_name"]],
            on="country_code",
            how="left",
        )
        .head(top_n)
        .copy()
    )
    detail["share_pct"] = detail["share"] * 100

    print("HSK10:", hs10_code)
    print(f"Official {reference_year} name:", summary["name_en"])
    print(f"12-month imports: ${summary['import_usd_bn']:,.2f}B")
    print(f"HHI: {summary['hhi']:.3f}")
    print(f"Top-1 share: {summary['top1_share']:.1%}")
    print(f"Top-3 share: {summary['top3_share']:.1%}")
    return detail[["country_code", "partner_name", "import_usd", "share_pct"]]


dependency_snapshot("8542321010")
'''
        ),
        md(
            """
## Interpretation and caveats

This screen is useful for finding **where to investigate next**, not for declaring that a product is automatically at risk.

- The country field is a KCS customs partner code. It is not a firm-level supplier identifier and should not automatically be treated as ultimate origin.
- HHI measures concentration, not substitutability. Two products with the same HHI may have very different technical switching costs.
- Imports are customs values in USD; price changes and exchange-rate movements can affect the value shares.
- This notebook uses the strict HSK10 canonical table. Rare non-HSK10 source rows are preserved separately rather than guessed into 10-digit codes.
- HSK10 is Korean national detail. For international product comparisons, HS6 is the safer common level.
- Official annual HSK names are linked from the KCS CLIP reference for the latest year. Product definitions can change across annual revisions, which is why this notebook limits itself to the latest 12 months.

### Where to go next

Good follow-up projects include:

1. tracking HHI changes through time to detect **rising concentration**,
2. comparing import concentration with export-market concentration,
3. building an HS6 forecasting benchmark, and
4. drilling from a concentrated HS6 category into the underlying Korean HSK10 details.
"""
        ),
    ]

    nb = nbf.v4.new_notebook(cells=cells)
    nb["metadata"] = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    }
    for idx, cell in enumerate(nb["cells"]):
        cell["id"] = f"sc{idx:02d}dep"

    nbf.write(nb, NOTEBOOK)

    metadata = {
        "id": "taeyangg4/korea-import-dependency-hsk10-supply-chain",
        "title": "Korea Import Dependency - HSK10 Supply Chain",
        "code_file": NOTEBOOK.name,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": False,
        "enable_gpu": False,
        "enable_tpu": False,
        "enable_internet": False,
        "machine_shape": "",
        "dataset_sources": ["taeyangg4/south-korea-customs-trade-hsk10"],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }
    METADATA.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    print(NOTEBOOK)
    print(METADATA)


if __name__ == "__main__":
    main()
