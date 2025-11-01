#!/usr/bin/env python3
"""
normalize_kaihuka.py - Convert 買掛台帳.TXT to an analysis-friendly TSV.

Usage:
    python3 normalize_kaihuka.py data/買掛台帳.TXT > normalized.tsv
    python3 normalize_kaihuka.py data/買掛台帳.TXT --output normalized.tsv
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

DEFAULT_HEADERS = [
    "ledger_type",
    "supplier_name",
    "entry_type",
    "block_index",
    "line_in_block",
    "source_line",
    "transaction_date",
    "description",
    "description_raw",
    "reference_1",
    "reference_2",
    "reference_3",
    "reference_4",
    "reference_5",
    "quantity",
    "quantity_note",
    "unit",
    "tax_rate",
    "unit_price",
    "amount",
    "payment",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize 買掛台帳.TXT into a tab-delimited table."
    )
    parser.add_argument("input", type=Path, help="Path to 買掛台帳.TXT")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Destination file (defaults to stdout)",
    )
    parser.add_argument(
        "--encoding",
        default="cp932",
        help="Source character encoding (default: cp932)",
    )
    parser.add_argument(
        "--delimiter",
        default="\t",
        help="Delimiter for the output file (default: tab)",
    )
    parser.add_argument(
        "--ledger-type",
        choices=("買掛", "売掛"),
        help="Label to place in the first column (auto-detected from filename if omitted)",
    )
    return parser.parse_args()


def sanitize_numeric(value: str) -> str:
    text = value.strip().replace(",", "")
    return text if text else ""


TARGET_MIN_COLUMNS = 18


def normalize_row(row: List[str]) -> List[str]:
    if len(row) < TARGET_MIN_COLUMNS:
        row = row + [""] * (TARGET_MIN_COLUMNS - len(row))
    return list(row)


def select_description(row: List[str], ledger_type: str) -> Tuple[str, str, int]:
    if ledger_type == "買掛":
        candidate_indices = (3, 4, 5, 6, 7, 8)
    else:
        candidate_indices = (5, 6, 3, 4, 7, 8)
    for idx in candidate_indices:
        if idx < len(row):
            original = row[idx]
            stripped = original.strip()
            if stripped:
                return original, stripped, idx

    for idx, original in enumerate(row):
        stripped = original.strip()
        if stripped:
            return original, stripped, idx

    return "", "", -1


def classify_entry(row: List[str], desc: str) -> str:
    if not row[0].strip() and desc:
        if "繰 越 残 高" in desc:
            return "opening_balance"
        if "計" in desc or "―" in desc:
            return "summary"
        if "残高" in desc:
            return "summary"
        return "supplier_header"

    label = desc.replace("　", "")
    if "支払" in label and not ("計" in label or "繰越" in label):
        return "payment"
    if "消費税" in label:
        return "tax"
    return "detail"


def extract_date(parts: List[str]) -> str:
    year, month, day = (part.strip() for part in parts[:3])
    if not (year and month and day):
        return ""
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def resolve_ledger_type(path: Path, override: Optional[str]) -> str:
    if override:
        return override

    name = path.name
    if "売" in name:
        return "売掛"
    if "買" in name:
        return "買掛"
    return "買掛"


def iter_entries(rows: Iterable[List[str]], ledger_type: str) -> Iterable[Tuple[str, ...]]:
    supplier_name = ""
    block_index = 0
    line_in_block = 0

    for source_line, raw_row in enumerate(rows, start=1):
        row = normalize_row(raw_row)
        description_raw, description, description_index = select_description(row, ledger_type)

        if not any(cell.strip() for cell in row):
            continue

        entry_type = classify_entry(row, description)

        if entry_type == "supplier_header":
            supplier_name = description
            block_index += 1
            line_in_block = 0
        else:
            line_in_block += 1

        reference_indices = (3, 4, 5, 6, 7, 8, 9)
        references: List[str] = []
        for idx in reference_indices:
            if idx == description_index:
                continue
            references.append(row[idx].strip() if idx < len(row) else "")
            if len(references) == 5:
                break
        while len(references) < 5:
            references.append("")

        def get(idx: int) -> str:
            return row[idx] if idx < len(row) else ""

        def numeric(idx: int) -> str:
            return sanitize_numeric(get(idx))

        if ledger_type == "売掛":
            quantity = numeric(11)
            quantity_note = sanitize_numeric(get(9)) or sanitize_numeric(get(10))
            unit = get(13).strip()
            tax_rate = numeric(12)
            unit_price = numeric(14)
            amount = numeric(15)
            payment = numeric(16) + numeric(17)
        else:
            quantity = numeric(9)
            quantity_note = sanitize_numeric(get(10))
            unit = get(11).strip()
            tax_rate = numeric(12)
            unit_price = numeric(13)
            amount = numeric(14)
            payment = numeric(15)

        output_row = (
            ledger_type,
            supplier_name,
            entry_type,
            str(block_index),
            str(line_in_block),
            str(source_line),
            extract_date(row),
            description,
            description_raw,
            references[0],
            references[1],
            references[2],
            references[3],
            references[4],
            quantity,
            quantity_note,
            unit,
            tax_rate,
            unit_price,
            amount,
            payment,
        )
        yield output_row


def main() -> None:
    args = parse_args()

    with args.input.open("r", encoding=args.encoding, errors="ignore") as fh:
        rows = list(csv.reader(fh))

    ledger_type = resolve_ledger_type(args.input, args.ledger_type)

    if args.output:
        output_handle = args.output.open("w", encoding="utf-8-sig", newline="")
        should_close = True
    else:
        output_handle = sys.stdout
        should_close = False
        output_handle.write("\ufeff")

    try:
        writer = csv.writer(output_handle, delimiter=args.delimiter, lineterminator="\n")
        writer.writerow(DEFAULT_HEADERS)
        for entry in iter_entries(rows, ledger_type):
            writer.writerow(entry)
    finally:
        if should_close:
            output_handle.close()


if __name__ == "__main__":
    main()
