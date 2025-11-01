#!/usr/bin/env bash

cd "$(dirname "$0")"

set -euo pipefail

# Check if app.py is already running in this directory
if pgrep -f "sales-ledger-viewer/\.venv/bin/python app\.py" > /dev/null 2>&1; then
    echo "app.py is already running"
    exit 0
fi

source .venv/bin/activate

mkdir -p data

python app.py
