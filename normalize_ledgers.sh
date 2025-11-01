#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"

DEFAULT_OUTPUT="${REPO_ROOT}/normalized_ledgers.tsv"
OUTPUT_PATH="${1:-$DEFAULT_OUTPUT}"

PURCHASE_SRC="${REPO_ROOT}/data/買掛台帳.TXT"
SALES_SRC="${REPO_ROOT}/data/売掛台帳.TXT"

if [[ ! -f "$PURCHASE_SRC" ]]; then
  echo "Error: Missing source file: $PURCHASE_SRC" >&2
  exit 1
fi

if [[ ! -f "$SALES_SRC" ]]; then
  echo "Error: Missing source file: $SALES_SRC" >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

purchase_tmp="${tmpdir}/purchase.tsv"
sales_tmp="${tmpdir}/sales.tsv"

python3 "${REPO_ROOT}/normalize.py" "$PURCHASE_SRC" --output "$purchase_tmp"
python3 "${REPO_ROOT}/normalize.py" "$SALES_SRC" --output "$sales_tmp"

cat "$purchase_tmp" > "$OUTPUT_PATH"
tail -n +2 "$sales_tmp" >> "$OUTPUT_PATH"

echo "Combined ledger written to: $OUTPUT_PATH"
