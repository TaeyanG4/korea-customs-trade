#!/usr/bin/env bash
set -euo pipefail

echo '[11/12] Rebuilding strict HSK10 with full coverage and annual HSK revision linkage...'
python ./normalize.py --require-full-coverage --overwrite

echo '[11/12] Building HS8/HS6/HS4/HS2 residual-aware analyst tables...'
python ./derive.py --overwrite

echo '[11/12] Running release-quality and Korean-text integrity gates...'
python ./release_qa.py

echo '[11/12] Stage 11 pipeline finished.'
