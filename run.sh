#!/usr/bin/env bash

cd "$(dirname "$0")"

set -euo pipefail

source .venv/bin/activate

mkdir -p data

python app.py
