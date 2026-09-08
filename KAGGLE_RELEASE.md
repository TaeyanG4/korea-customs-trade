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

## Private release status

The target handle is `taeyangg4/south-korea-customs-trade-hsk10`. The private-first release has been completed and validated.

- Dataset Version 2: `Ready`
- Visibility: **Private**
- Current Usability: **7.65/10** (`0.7647059`)
- Update frequency: monthly
- Cover image: present
- Live-valid tags: `business`, `tabular`, `economics`, `time series analysis`, `government`, `asia`, `international relations`
- Starter Notebook: `taeyangg4/south-korea-trade-in-5-minutes-hs6-quickstart`
- Notebook Version 3: `COMPLETE` in Kaggle runtime
- Notebook visibility: **Private**

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

The private validation already confirmed the Dataset files, metadata, cover, provenance, monthly frequency, and starter Notebook runtime. Do not create another full Dataset version solely because Kaggle's files/metadata APIs report empty file descriptions or zero columns; the same API behavior was observed on public Usability-10 datasets.

## Usability / medal follow-up

The concise HS6 starter Notebook already exists and has been validated privately:

**South Korea Trade in 5 Minutes — HS6 Quickstart**

The remaining release sequence is:

1. Make the Dataset public only after explicit approval.
2. Make the already validated starter Notebook public and preserve its Dataset source association.
3. Re-check Dataset public visibility, Notebook public visibility, Dataset `kernel_count`, and Usability after Kaggle propagation.
4. If Usability remains below 10.0, investigate only the residual gap; do not repeat the ~1.189 GB upload without evidence that a new Dataset version is required.

A public Notebook is strongly indicated by the sampled Usability-10 ecosystem, but it is not treated as a guaranteed score change. Final Usability must be verified after publication. Deeper follow-up notebooks can then cover semiconductor exports, partner concentration, and HSK10 supply-chain dependence.
