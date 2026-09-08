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
- Current Usability: **8.24/10** (`0.8235294`)
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

The public Notebook raised the Dataset from the private-first score, and direct Kaggle usability inspection now identifies only two remaining components:

- `fileDescriptionScore = 0`
- `columnDescriptionScore = 0`

Every other Usability component is `1`. Local release metadata already contains descriptions for all 16 files and all 158 represented columns. Kaggle CLI 2.2.4 sends those descriptions correctly, but live OAuth metadata updates do not persist them into Data Viewer v3. A fresh tiny probe Dataset reproduced the same behavior, so this is not evidence that the 1.19 GB trade package needs another blind upload.

The remaining sequence is therefore:

1. Persist all file and column descriptions into Kaggle's Data Viewer metadata store using a supported authenticated path.
2. Re-check `fileDescriptionScore=1`, `columnDescriptionScore=1`, and final `score=1.0`.
3. Only after the score is verified at 10.00, treat the Usability milestone as complete and shift focus to sustained updates and Dataset-medal discovery/quality work.
