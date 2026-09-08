$ErrorActionPreference = 'Stop'

if (-not $env:KCS_SERVICE_KEY) {
    throw 'Set KCS_SERVICE_KEY first. Example: $env:KCS_SERVICE_KEY="YOUR_KEY"'
}

python .\pilot.py --data-dir .\data quick --country US --year 2025
