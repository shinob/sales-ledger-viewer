#!/usr/bin/env bash

set -euo pipefail

echo "== 仮想環境構築 =="
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

echo "== サンプルデータ登録 =="
cp -r sample_data data
./normalize_ledgers.sh
