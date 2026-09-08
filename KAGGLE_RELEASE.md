# Kaggle release checklist

Target: **Usability 10.00 + Dataset medal** without over-cleaning official source data.

## Build

PowerShell:

```powershell
.\run_build_release.ps1
```

Git Bash:

```bash
bash ./run_build_release.sh
```

The output is written to `release/kaggle/` and is intentionally ignored by Git.

## Pre-publish checks

- `data/audits/release_qa/release_qa.json` has `release_gate_pass=true`.
- `release_manifest.json` row counts and hashes are present.
- `dataset-metadata.json` contains title, subtitle, description, tags, provenance, monthly update frequency, license, file descriptions, and full field descriptions for tabular files.
- `dataset-cover-image.jpg` is present.
- UTF-8 text gate passes; Korean names contain no decoding damage.
- Source exception and negative-weight warning files are included.
- No API key, `.env`, raw XML, local absolute source paths, or bulky internal audit manifests are included.

## Create privately first

The target handle is `taeyangg4/south-korea-customs-trade-hsk10`. A pre-upload search on 2026-09-09 found no existing dataset with that handle/title.

Use the guarded upload wrapper. It verifies the release QA result, release manifest, and dataset ID before invoking Kaggle. The wrapper intentionally does **not** add `--public`, so the first upload is private.

Git Bash:

```bash
bash ./run_kaggle_private_upload.sh --preflight-only
bash ./run_kaggle_private_upload.sh
```

PowerShell:

```powershell
.\run_kaggle_private_upload.ps1 -PreflightOnly
.\run_kaggle_private_upload.ps1
```

Equivalent raw CLI command:

```bash
kaggle datasets create -p release/kaggle -t
```

After upload, verify the Data page, descriptions, license/provenance, cover image, and Usability checklist in the Kaggle UI. Only then make the dataset public.

## Usability / medal follow-up

Kaggle's progression guidance recommends a complete 10.0 usability score and an example Notebook. After the dataset is published, create a concise starter Notebook using HS6 and link it from the dataset. Suggested first Notebook:

**South Korea Trade in 5 Minutes — HS6 Quickstart**

Then publish deeper notebooks such as semiconductor exports, partner concentration, and HSK10 supply-chain dependence.
