import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_DIR = REPO_ROOT / "kaggle_notebooks" / "hs6_quickstart"
DATASET_SOURCE = "taeyangg4/south-korea-customs-trade-hsk10"


def _read_notebook(directory: Path, filename: str):
    return json.loads((directory / filename).read_text(encoding="utf-8"))


def _assert_clean_source_notebook(notebook):
    assert all(cell.get("id") for cell in notebook["cells"])
    for cell in notebook["cells"]:
        if cell.get("cell_type") == "code":
            assert cell.get("execution_count") is None
            assert cell.get("outputs", []) == []

    source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])
    assert "/kaggle/input/south-korea-customs-trade-hsk10" not in source
    assert "/kaggle/input" in source
    assert "\ufffd" not in source
    return source


def test_hs6_quickstart_metadata_and_source_are_release_safe():
    metadata = json.loads((NOTEBOOK_DIR / "kernel-metadata.json").read_text(encoding="utf-8"))
    assert metadata["id"] == "taeyangg4/south-korea-trade-in-5-minutes-hs6-quickstart"
    assert metadata["is_private"] is False
    assert metadata["dataset_sources"] == [DATASET_SOURCE]

    notebook = _read_notebook(NOTEBOOK_DIR, "south_korea_trade_hs6_quickstart.ipynb")
    source = _assert_clean_source_notebook(notebook)
    assert "trade_hs6_monthly.parquet" in source
    assert source.count("?") == 1
    assert "Which product groups lead exports?" in source


def test_supply_chain_notebook_is_public_and_release_safe():
    directory = REPO_ROOT / "kaggle_notebooks" / "import_dependency_hsk10"
    metadata = json.loads((directory / "kernel-metadata.json").read_text(encoding="utf-8"))
    assert metadata["id"] == "taeyangg4/korea-import-dependency-hsk10-supply-chain"
    assert metadata["is_private"] is False
    assert metadata["dataset_sources"] == [DATASET_SOURCE]

    notebook = _read_notebook(directory, "korea_import_dependency_hsk10.ipynb")
    source = _assert_clean_source_notebook(notebook)
    assert "trade_hs10_monthly.parquet" in source
    assert "hsk_code_reference.parquet" in source
    assert "Concentration-weighted import exposure" in source
    assert "Top-1 partner share" in source
    assert "HHI" in source


def test_hs6_ml_forecast_notebook_is_public_and_leakage_aware():
    directory = REPO_ROOT / "kaggle_notebooks" / "hs6_import_forecast_ml"
    metadata = json.loads((directory / "kernel-metadata.json").read_text(encoding="utf-8"))
    assert metadata["id"] == "taeyangg4/forecast-korea-imports-hs6-ml-vs-naive"
    assert metadata["is_private"] is False
    assert metadata["dataset_sources"] == [DATASET_SOURCE]

    notebook = _read_notebook(directory, "korea_hs6_import_forecast_ml.ipynb")
    source = _assert_clean_source_notebook(notebook)
    assert "trade_hs6_monthly.parquet" in source
    assert "GradientBoostingRegressor" in source
    assert 'loss="huber"' in source
    assert "seasonal naive" in source.lower()
    assert "test_start_period = end_period - 11" in source
    assert "selection_start_period = train_end_period - 23" in source
