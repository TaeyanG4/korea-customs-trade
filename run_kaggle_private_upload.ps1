param(
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$releaseDir = Join-Path $root 'release\kaggle'
$datasetId = 'taeyangg4/south-korea-customs-trade-hsk10'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$qaPath = Join-Path $root 'data\audits\release_qa\release_qa.json'
$metadataPath = Join-Path $releaseDir 'dataset-metadata.json'
$manifestPath = Join-Path $releaseDir 'release_manifest.json'

foreach ($path in @($qaPath, $metadataPath, $manifestPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing required file: $path"
    }
}

$qa = Get-Content -LiteralPath $qaPath -Raw -Encoding UTF8 | ConvertFrom-Json
$metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json

if ($qa.release_gate_pass -ne $true) {
    throw 'Release QA has not passed; refusing Kaggle upload.'
}
if ($metadata.id -ne $datasetId) {
    throw "Unexpected dataset id: $($metadata.id)"
}
if ($manifest.quality.release_gate_pass -ne $true) {
    throw 'Release manifest does not record a passing release gate.'
}

Write-Host '[12/12] Kaggle private-upload preflight PASS'
Write-Host "dataset_id=$datasetId"
Write-Host "coverage=$($manifest.coverage.start_month)..$($manifest.coverage.end_month)"
Write-Host "canonical_hsk10_rows=$($manifest.coverage.canonical_hsk10_rows)"
Write-Host "release_files=$((Get-ChildItem -LiteralPath $releaseDir -File).Count)"

if ($PreflightOnly) {
    Write-Host '[12/12] Preflight-only mode complete; no upload was attempted.'
    exit 0
}

Write-Host '[12/12] Creating Kaggle dataset privately (no --public flag)...'
& kaggle datasets create -p $releaseDir -t
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host '[12/12] Kaggle dataset create command finished. Current status:'
& kaggle datasets status $datasetId --format json
exit $LASTEXITCODE
