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

## Public release status

The target handle is `taeyangg4/south-korea-customs-trade-hsk10`. The private-first release was validated before publication, and the Dataset and starter Notebook are now public.

- Dataset Version 2: `Ready`
- Visibility: **Public**
- Current Usability: **10.00/10** (`1.0`)
- Update frequency: monthly
- Cover image: present
- Live-valid tags: `business`, `tabular`, `economics`, `time series analysis`, `government`, `asia`, `international relations`
- Starter Notebook: `taeyangg4/south-korea-trade-in-5-minutes-hs6-quickstart`
- Notebook Version 3: `COMPLETE` in Kaggle runtime
- Notebook visibility: **Public**

The guarded upload wrapper remains the reproducible path for future private version uploads. It verifies the release QA result, release manifest, and dataset ID before invoking Kaggle and deliberately does **not** add `--public`.

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

The equivalent raw CLI command used for the **initial private creation** was:

```bash
kaggle datasets create -p release/kaggle -t
```

Now that the Dataset exists, future data/metadata releases should use a Dataset version update rather than repeating `datasets create`.

The private validation already confirmed the Dataset files, metadata, cover, provenance, monthly frequency, and starter Notebook runtime. Do not create another ~1.19 GB Dataset version solely because Kaggle's legacy metadata response omits file/column descriptions; the same response behavior is visible on public Usability-10 datasets.

## Usability / medal follow-up

The concise HS6 starter Notebook is public and validated:

**South Korea Trade in 5 Minutes — HS6 Quickstart**

The public Notebook raised the Dataset from the private-first score. The final remaining gap was the Data Viewer metadata store: local release metadata already contained descriptions for all 16 files and all 158 represented columns, but token-authenticated CLI/MCP metadata updates did not persist those two scoring components in this environment.

The descriptions were finally persisted through Kaggle's authenticated same-origin Data Viewer update endpoint from the user's logged-in Dataset page. All 16 files completed successfully and all 158 column descriptions were written while preserving Kaggle's server-inferred column types.

Independent post-write verification reports:

- `fileDescriptionScore = 1`
- `columnDescriptionScore = 1`
- every other Usability component = `1`
- final `score = 1.0` = **10.00/10**

The Usability milestone is therefore complete. Future work should preserve this metadata during monthly releases and focus on Dataset-medal discovery, sustained updates, notebook usefulness, and community adoption instead of further score chasing.
