import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_DIR = REPO_ROOT / "kaggle_notebooks" / "hs6_quickstart"


def test_hs6_quickstart_metadata_and_source_are_release_safe():
    metadata = json.loads((NOTEBOOK_DIR / "kernel-metadata.json").read_text(encoding="utf-8"))
    assert metadata["id"] == "taeyangg4/south-korea-trade-in-5-minutes-hs6-quickstart"
    assert metadata["is_private"] is False
    assert metadata["dataset_sources"] == ["taeyangg4/south-korea-customs-trade-hsk10"]

    notebook = json.loads(
        (NOTEBOOK_DIR / "south_korea_trade_hs6_quickstart.ipynb").read_text(encoding="utf-8")
    )
    assert all(cell.get("id") for cell in notebook["cells"])

    source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])
    assert "/kaggle/input/south-korea-customs-trade-hsk10" not in source
    assert "/kaggle/input" in source
    assert "trade_hs6_monthly.parquet" in source
    assert "\ufffd" not in source
    assert source.count("?") == 1
    assert "Which product groups lead exports?" in source
