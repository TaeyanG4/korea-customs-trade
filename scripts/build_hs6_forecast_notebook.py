from __future__ import annotations

import json
from pathlib import Path

import nbformat as nbf


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kaggle_notebooks" / "hs6_import_forecast_ml"
NOTEBOOK = OUT / "korea_hs6_import_forecast_ml.ipynb"
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
# Forecast Korea Imports - HS6 Machine Learning vs Naive Baselines

Can a compact machine-learning model improve on simple time-series baselines for South Korea's largest imported product groups?

This notebook builds a **leakage-aware monthly forecasting benchmark** from the South Korea Customs Trade Dataset:

1. select the top 100 HS6 import groups using **training-period data only**,
2. aggregate monthly imports over a consistent geographic-partner universe,
3. create lag and rolling features using only information available before each target month,
4. hold out the latest 12 complete months, and
5. compare a `HistGradientBoostingRegressor` against two strong baselines:
   - previous month (`lag-1`), and
   - same month one year earlier (`seasonal naive`, lag-12).

The goal is not to claim that ML always wins. A useful benchmark should show **how much** it helps, and when a simple rule remains hard to beat.

**Source:** Korea Customs Service public data.
**Forecast target:** monthly import value in USD for each selected HS6 code.
**Analytical partner universe:** current UN geographic matches plus `TW`, excluding `KR` and KCS special/aggregate codes.
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

from sklearn.ensemble import GradientBoostingRegressor
from sklearn.inspection import permutation_importance

pd.set_option("display.max_columns", 30)
pd.set_option("display.float_format", lambda x: f"{x:,.4f}")

DATA = None
kaggle_input = Path("/kaggle/input")
if kaggle_input.exists():
    matches = list(kaggle_input.rglob("trade_hs6_monthly.parquet"))
    for match in matches:
        candidate = match.parent
        if (
            (candidate / "country_reference.csv").exists()
            and (candidate / "release_manifest.json").exists()
        ):
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
## 1. Define the temporal split before touching the model

The latest **12 complete months** are the test set. Everything before that is training data.

The top-100 HS6 portfolio is selected from the final 24 months of the **training period only**. This matters: choosing products using future test values would be a subtle form of leakage.

We keep roughly 7.5 years of pre-test history, which is more than enough for annual seasonal lags while keeping the Kaggle runtime light.
"""
        ),
        code(
            r'''
manifest = json.loads((DATA / "release_manifest.json").read_text(encoding="utf-8"))

dataset_start = pd.Period(manifest["coverage"]["start_month"], freq="M")
end_period = pd.Period(manifest["coverage"]["end_month"], freq="M")
test_start_period = end_period - 11
train_end_period = test_start_period - 1
selection_start_period = train_end_period - 23
history_start_period = max(dataset_start, train_end_period - 90)

end_month = end_period.strftime("%Y%m")
test_start = test_start_period.strftime("%Y%m")
train_end = train_end_period.strftime("%Y%m")
selection_start = selection_start_period.strftime("%Y%m")
history_start = history_start_period.strftime("%Y%m")

print(f"History used: {history_start} -> {end_month}")
print(f"Top-HS6 selection window: {selection_start} -> {train_end}")
print(f"Training targets end: {train_end}")
print(f"Held-out test: {test_start} -> {end_month}")
'''
        ),
        code(
            r'''
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

hs6_ds = ds.dataset(DATA / "trade_hs6_monthly.parquet", format="parquet")
print(f"Geographic partner codes used: {len(geo_codes):,}")
'''
        ),
        md(
            """
## 2. Select the top 100 HS6 groups without looking at the test period

Only the selection window ending at `train_end` is used to decide which products enter the benchmark.
"""
        ),
        code(
            r'''
TOP_N = 100

selection = hs6_ds.to_table(
    filter=(
        (ds.field("month") >= selection_start)
        & (ds.field("month") <= train_end)
        & ds.field("country_code").isin(sorted(geo_codes))
    ),
    columns=["hs6", "import_usd"],
).to_pandas()

top_codes = (
    selection.groupby("hs6")["import_usd"]
    .sum()
    .nlargest(TOP_N)
    .index.astype(str)
    .tolist()
)

print(f"Rows scanned for leakage-safe product selection: {len(selection):,}")
print(f"Selected HS6 groups: {len(top_codes):,}")
print("First 15 HS6 codes:", top_codes[:15])
'''
        ),
        md(
            """
## 3. Build a complete monthly panel

We read only the selected HS6 codes over the modeling history and sum across the analytical geographic-partner universe.

A complete `month x HS6` grid is then created. A missing code-month inside this selected portfolio is treated as zero observed imports for that analytical universe.
"""
        ),
        code(
            r'''
history = hs6_ds.to_table(
    filter=(
        (ds.field("month") >= history_start)
        & (ds.field("month") <= end_month)
        & ds.field("country_code").isin(sorted(geo_codes))
        & ds.field("hs6").isin(top_codes)
    ),
    columns=["month", "hs6", "import_usd"],
).to_pandas()

monthly = history.groupby(["month", "hs6"], as_index=False)["import_usd"].sum()
all_months = pd.period_range(history_start, end_month, freq="M").strftime("%Y%m")
grid = pd.MultiIndex.from_product([all_months, top_codes], names=["month", "hs6"]).to_frame(index=False)
panel = (
    grid.merge(monthly, on=["month", "hs6"], how="left")
    .fillna({"import_usd": 0})
    .sort_values(["hs6", "month"])
    .reset_index(drop=True)
)

print(f"Source HS6 rows read: {len(history):,}")
print(f"Complete monthly panel rows: {len(panel):,}")
print(f"Panel months: {panel['month'].min()} -> {panel['month'].max()}")
'''
        ),
        md(
            """
## 4. Leakage-safe lag features

Every predictor below is available **before** the target month:

- imports 1, 2, 3, 6, and 12 months ago,
- rolling means over the previous 3, 6, and 12 months,
- sine/cosine month-of-year seasonality.

Import values are log-transformed for the model because product scales differ by orders of magnitude.
"""
        ),
        code(
            r'''
panel["month_number"] = panel["month"].str[-2:].astype(int)
panel["month_sin"] = np.sin(2 * np.pi * panel["month_number"] / 12)
panel["month_cos"] = np.cos(2 * np.pi * panel["month_number"] / 12)

grouped = panel.groupby("hs6")["import_usd"]
for lag in [1, 2, 3, 6, 12]:
    panel[f"lag{lag}"] = grouped.shift(lag)

for window in [3, 6, 12]:
    panel[f"roll{window}"] = grouped.transform(
        lambda s: s.shift(1).rolling(window).mean()
    )

raw_history_features = [
    "lag1", "lag2", "lag3", "lag6", "lag12", "roll3", "roll6", "roll12"
]
for column in raw_history_features:
    panel[f"log_{column}"] = np.log1p(panel[column])

feature_columns = [
    "month_sin", "month_cos",
    "log_lag1", "log_lag2", "log_lag3", "log_lag6", "log_lag12",
    "log_roll3", "log_roll6", "log_roll12",
]

model_frame = panel.dropna(subset=raw_history_features).copy()
train = model_frame.loc[model_frame["month"] <= train_end].copy()
test = model_frame.loc[
    (model_frame["month"] >= test_start) & (model_frame["month"] <= end_month)
].copy()

print(f"Training rows: {len(train):,}")
print(f"Test rows: {len(test):,}")
print(f"Test HS6 groups: {test['hs6'].nunique():,}")
'''
        ),
        md(
            """
## 5. Baselines first, then machine learning

We benchmark against:

- **Lag-1 persistence:** next month equals the previous month.
- **Seasonal naive:** next month equals the same month one year earlier.

The ML model is `GradientBoostingRegressor` with Huber loss, trained on `log1p(import_usd)` and converted back to USD after prediction. Huber loss makes the fit less sensitive to extreme monthly shocks than ordinary squared-error boosting.

We report:

- **WAPE** = total absolute error / total actual imports. This gives economically large products more weight.
- **RMSLE** = error on the log scale. This is less dominated by the very largest products.
"""
        ),
        code(
            r'''
X_train = train[feature_columns]
y_train_log = np.log1p(train["import_usd"])
X_test = test[feature_columns]
y_test = test["import_usd"].to_numpy()

model = GradientBoostingRegressor(
    n_estimators=300,
    learning_rate=0.03,
    max_depth=3,
    loss="huber",
    random_state=42,
)
model.fit(X_train, y_train_log)

pred_model = np.expm1(model.predict(X_test)).clip(0)
pred_lag1 = test["lag1"].to_numpy()
pred_seasonal = test["lag12"].to_numpy()

def wape(actual, predicted):
    return np.abs(actual - predicted).sum() / np.abs(actual).sum()

def rmsle(actual, predicted):
    return np.sqrt(np.mean((np.log1p(actual) - np.log1p(predicted)) ** 2))

score_table = pd.DataFrame(
    [
        {"model": "Lag-1 persistence", "WAPE": wape(y_test, pred_lag1), "RMSLE": rmsle(y_test, pred_lag1)},
        {"model": "Seasonal naive (lag-12)", "WAPE": wape(y_test, pred_seasonal), "RMSLE": rmsle(y_test, pred_seasonal)},
        {"model": "GradientBoosting (Huber)", "WAPE": wape(y_test, pred_model), "RMSLE": rmsle(y_test, pred_model)},
    ]
).sort_values("WAPE")

score_table
'''
        ),
        code(
            r'''
model_wape = float(score_table.loc[score_table["model"].eq("GradientBoosting (Huber)"), "WAPE"].iloc[0])
lag1_wape = float(score_table.loc[score_table["model"].eq("Lag-1 persistence"), "WAPE"].iloc[0])
seasonal_wape = float(score_table.loc[score_table["model"].eq("Seasonal naive (lag-12)"), "WAPE"].iloc[0])

print(f"ML relative WAPE improvement vs seasonal naive: {1 - model_wape / seasonal_wape:.1%}")
print(f"ML relative WAPE improvement vs lag-1 persistence: {1 - model_wape / lag1_wape:.1%}")

plot_scores = score_table.sort_values("WAPE", ascending=False)
fig, ax = plt.subplots(figsize=(8, 4))
ax.barh(plot_scores["model"], plot_scores["WAPE"] * 100)
ax.set_xlabel("WAPE (%) - lower is better")
ax.set_ylabel("")
ax.set_title(f"Held-out forecast accuracy: {test_start} to {end_month}")
plt.tight_layout()
plt.show()
'''
        ),
        md(
            """
## 6. Where does ML help most?

The table compares absolute forecast error by HS6. Positive `relative_improvement_vs_seasonal` means the ML model beat the seasonal-naive baseline for that product group.
"""
        ),
        code(
            r'''
results = test[["month", "hs6", "import_usd", "lag1", "lag12"]].copy()
results["pred_ml"] = pred_model
results["abs_error_ml"] = np.abs(results["import_usd"] - results["pred_ml"])
results["abs_error_seasonal"] = np.abs(results["import_usd"] - results["lag12"])
results["abs_error_lag1"] = np.abs(results["import_usd"] - results["lag1"])

by_product = (
    results.groupby("hs6", as_index=False)
    .agg(
        actual_import_usd=("import_usd", "sum"),
        ml_abs_error=("abs_error_ml", "sum"),
        seasonal_abs_error=("abs_error_seasonal", "sum"),
        lag1_abs_error=("abs_error_lag1", "sum"),
    )
)
by_product["actual_import_usd_bn"] = by_product["actual_import_usd"] / 1e9
by_product["relative_improvement_vs_seasonal"] = 1 - (
    by_product["ml_abs_error"] / by_product["seasonal_abs_error"]
)
by_product["relative_improvement_vs_lag1"] = 1 - (
    by_product["ml_abs_error"] / by_product["lag1_abs_error"]
)

by_product.nlargest(20, "actual_import_usd")[[
    "hs6", "actual_import_usd_bn", "relative_improvement_vs_seasonal", "relative_improvement_vs_lag1"
]]
'''
        ),
        md(
            """
## 7. Actual vs forecast for the largest held-out product groups

We plot four of the largest HS6 groups in the test period. This makes it easier to see whether an aggregate metric is hiding obvious failure modes.
"""
        ),
        code(
            r'''
largest_test_codes = (
    results.groupby("hs6")["import_usd"].sum().nlargest(4).index.tolist()
)

for code_value in largest_test_codes:
    view = results.loc[results["hs6"].eq(code_value)].sort_values("month").copy()
    view["actual_bn"] = view["import_usd"] / 1e9
    view["ml_bn"] = view["pred_ml"] / 1e9
    view["seasonal_bn"] = view["lag12"] / 1e9

    ax = view.plot(
        x="month",
        y=["actual_bn", "ml_bn", "seasonal_bn"],
        figsize=(10, 4),
        marker="o",
    )
    ax.set_title(f"HS6 {code_value} - held-out monthly imports")
    ax.set_ylabel("USD billions")
    ax.set_xlabel("Month")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()
'''
        ),
        md(
            """
## 8. Which features matter to the model?

Permutation importance is calculated on the held-out set using log-scale absolute error. It measures how much validation performance deteriorates when a feature is randomly shuffled.
"""
        ),
        code(
            r'''
importance = permutation_importance(
    model,
    X_test,
    np.log1p(y_test),
    scoring="neg_mean_absolute_error",
    n_repeats=8,
    random_state=42,
)

importance_df = pd.DataFrame(
    {
        "feature": feature_columns,
        "importance": importance.importances_mean,
    }
).sort_values("importance")

fig, ax = plt.subplots(figsize=(8, 5))
ax.barh(importance_df["feature"], importance_df["importance"])
ax.set_title("Permutation importance on the held-out period")
ax.set_xlabel("Increase in log-scale MAE when shuffled")
ax.set_ylabel("")
plt.tight_layout()
plt.show()

importance_df.sort_values("importance", ascending=False)
'''
        ),
        md(
            """
## 9. Refit on all available months and forecast the next month

After evaluating the model honestly on the 12-month holdout, we can refit the same specification using **all currently available target months** and create a one-step-ahead forecast for the selected top-100 HS6 portfolio.

These are model estimates, not official KCS forecasts.
"""
        ),
        code(
            r'''
full_train = model_frame.loc[model_frame["month"] <= end_month].copy()
final_model = GradientBoostingRegressor(
    n_estimators=300,
    learning_rate=0.03,
    max_depth=3,
    loss="huber",
    random_state=42,
)
final_model.fit(full_train[feature_columns], np.log1p(full_train["import_usd"]))

next_period = end_period + 1
next_month_number = next_period.month
next_rows = []

for code_value in top_codes:
    values = (
        panel.loc[panel["hs6"].eq(code_value)]
        .sort_values("month")["import_usd"]
        .to_numpy()
    )
    row = {
        "hs6": code_value,
        "month_sin": np.sin(2 * np.pi * next_month_number / 12),
        "month_cos": np.cos(2 * np.pi * next_month_number / 12),
        "log_lag1": np.log1p(values[-1]),
        "log_lag2": np.log1p(values[-2]),
        "log_lag3": np.log1p(values[-3]),
        "log_lag6": np.log1p(values[-6]),
        "log_lag12": np.log1p(values[-12]),
        "log_roll3": np.log1p(values[-3:].mean()),
        "log_roll6": np.log1p(values[-6:].mean()),
        "log_roll12": np.log1p(values[-12:].mean()),
    }
    next_rows.append(row)

next_features = pd.DataFrame(next_rows)
next_features["forecast_import_usd"] = np.expm1(
    final_model.predict(next_features[feature_columns])
).clip(0)
next_features["forecast_import_usd_bn"] = next_features["forecast_import_usd"] / 1e9

print("Forecast month:", next_period.strftime("%Y%m"))
next_features.nlargest(20, "forecast_import_usd")[["hs6", "forecast_import_usd_bn"]]
'''
        ),
        md(
            """
## What this benchmark does - and does not - prove

- **No random train/test split:** the latest 12 months are held out chronologically.
- **No test-period product selection:** the top-100 portfolio is chosen using training data only.
- **Strong baselines are mandatory:** monthly customs data often has persistence and seasonality that are hard to beat.
- The geographic-partner universe deliberately excludes KCS aggregate/special codes to avoid obvious double counting; it is not presented as an independently published Korea-wide total.
- HS6 is the internationally comparable product boundary. The underlying Dataset also provides Korean HSK10 detail for deeper product-specific work.
- The model uses customs values only. It does not include exchange rates, commodity prices, policy changes, inventories, or macroeconomic covariates.
- A forecast is not a causal explanation. Large errors are useful signals for where richer features or structural knowledge may be needed.

### Next experiments

1. rolling-origin cross-validation instead of a single 12-month holdout,
2. separate models by HS2/industry family,
3. add commodity prices and FX rates from properly licensed external sources,
4. forecast partner-level imports rather than national HS6 aggregates, and
5. compare tree models with classical ETS/ARIMA models on the same split.
"""
        ),
    ]

    nb = nbf.v4.new_notebook(cells=cells)
    nb["metadata"] = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    }
    for idx, cell in enumerate(nb["cells"]):
        cell["id"] = f"ml{idx:02d}hs6"

    nbf.write(nb, NOTEBOOK)

    metadata = {
        "id": "taeyangg4/forecast-korea-imports-hs6-ml-vs-naive",
        "title": "Forecast Korea Imports - HS6 ML vs Naive",
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
