$ErrorActionPreference = 'Stop'

Write-Host '[11/12] Rebuilding strict HSK10 with full coverage and annual HSK revision linkage...'
python .\normalize.py --require-full-coverage --overwrite

Write-Host '[11/12] Building HS8/HS6/HS4/HS2 residual-aware analyst tables...'
python .\derive.py --overwrite

Write-Host '[11/12] Running release-quality and Korean-text integrity gates...'
python .\release_qa.py

Write-Host '[11/12] Stage 11 pipeline finished.'
