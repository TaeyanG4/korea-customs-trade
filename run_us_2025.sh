#!/usr/bin/env bash
set -euo pipefail

: "${KCS_SERVICE_KEY:?Set KCS_SERVICE_KEY first}"
python pilot.py --data-dir data quick --country US --year 2025
