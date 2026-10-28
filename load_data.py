"""Load data/sales.csv into SQLite with validation and a data-quality report.

Run from the project root with the virtual environment active:
    python load_data.py
    python load_data.py --csv data/sales.csv --db data/sales.db

Cleaning rules (see README for the reasoning):
- Dates must be DD-MM-YYYY and are stored as YYYY-MM-DD.
- quantity must be a positive whole number; unit_price must be positive;
  discount_amount must be between 0 and the line total.
- Revenue = quantity * unit_price - discount_amount (discount applies once per line).
- Only rows with status 'Completed' count toward revenue. Other statuses
  (for example 'Returned') are stored but excluded from revenue calculations.
- Rows failing any rule are rejected and saved in the rejected_rows table.
- A repeated transaction_id is rejected as a duplicate (the first one is kept).
"""

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from app.database import (
    BASE_DIR,
    create_schema,
    drop_schema,
    get_db_path,
    open_writable_connection,
)

DATE_FORMAT = "%d-%m-%Y"
REVENUE_STATUS = "Completed"

REQUIRED_COLUMNS = [
    "transaction_id",
    "order_date",
    "product",
    "category",
    "region",
    "sales_channel",
    "quantity",
    "unit_price",
    "discount_amount",
    "status",
]
TEXT_FIELDS = ["transaction_id", "product", "category", "region", "sales_channel", "status"]

INSERT_SALES_SQL = """
    INSERT INTO sales (
        transaction_id, order_date, order_month, product, category, region,
        sales_channel, quantity, unit_price, discount_amount, status,
        revenue, counts_toward_revenue
    ) VALUES (
        :transaction_id, :order_date, :order_month, :product, :category, :region,
        :sales_channel, :quantity, :unit_price, :discount_amount, :status,
        :revenue, :counts_toward_revenue
    )
"""
INSERT_REJECTED_SQL = """
    INSERT INTO rejected_rows (source_row, transaction_id, reason, raw_values)
    VALUES (?, ?, ?, ?)
"""

MAX_REJECTED_PRINTED = 25


@dataclass
class RejectedRow:
    source_row: int
    transaction_id: str
    reasons: list
    raw: dict


@dataclass
class CleaningResult:
    rows_read: int = 0
    accepted: list = field(default_factory=list)
    rejected: list = field(default_factory=list)


def read_csv(csv_path: Path) -> pd.DataFrame:
    """Read the CSV as text so that we control all type conversion ourselves."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    try:
        df = pd.read_csv(
            csv_path,
            dtype=str,
            keep_default_na=False,
            skip_blank_lines=False,
            skipinitialspace=True,
            encoding="utf-8-sig",
        )
    except pd.errors.EmptyDataError as exc:
        raise ValueError("The CSV file is empty.") from exc
    except pd.errors.ParserError as exc:
        raise ValueError(f"The CSV file could not be parsed: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError("The CSV file is not valid UTF-8 text.") from exc

    df.columns = [str(col).strip().lower() for col in df.columns]
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"The CSV is missing required columns: {', '.join(missing)}")
    if df.empty:
        raise ValueError("The CSV has a header row but no data rows.")
    return df


def _parse_number(text: str, name: str, problems: list) -> Optional[float]:
    """Convert text to a finite float, recording a problem if that is not possible."""
    if text == "":
        problems.append(f"missing {name}")
        return None
    try:
        value = float(text)
    except ValueError:
        problems.append(f"invalid {name} '{text}' (not a number)")
        return None
    if not math.isfinite(value):
        problems.append(f"invalid {name} '{text}' (not a finite number)")
        return None
    return value


def validate_row(raw: dict):
    """Validate one CSV row.

    Returns (clean_row, problems). clean_row is None when problems is not empty.
    """
    problems: list = []
    row = {name: str(raw.get(name, "") or "").strip() for name in REQUIRED_COLUMNS}

    for name in TEXT_FIELDS:
        if not row[name]:
            problems.append(f"missing {name}")

    order_date = None
    if not row["order_date"]:
        problems.append("missing order_date")
    else:
        try:
            order_date = datetime.strptime(row["order_date"], DATE_FORMAT).date()
        except ValueError:
            problems.append(f"invalid order_date '{row['order_date']}' (expected DD-MM-YYYY)")

    quantity = None
    quantity_value = _parse_number(row["quantity"], "quantity", problems)
    if quantity_value is not None:
        if not quantity_value.is_integer():
            problems.append(f"quantity must be a whole number (got {row['quantity']})")
        elif quantity_value < 0:
            problems.append(
                f"negative quantity ({row['quantity']}); in this dataset returns are "
                "marked by Status, so this row needs manual review"
            )
        elif quantity_value == 0:
            problems.append("quantity must be greater than zero (got 0)")
        else:
            quantity = int(quantity_value)

    unit_price = _parse_number(row["unit_price"], "unit_price", problems)
    if unit_price is not None and unit_price <= 0:
        problems.append(f"unit_price must be greater than zero (got {row['unit_price']})")
        unit_price = None

    discount = _parse_number(row["discount_amount"], "discount_amount", problems)
    if discount is not None and discount < 0:
        problems.append(f"discount_amount must not be negative (got {row['discount_amount']})")
        discount = None

    if quantity is not None and unit_price is not None and discount is not None:
        line_total = quantity * unit_price
        if discount > line_total:
            problems.append(
                f"discount_amount ({row['discount_amount']}) exceeds the line total ({line_total:g})"
            )

    if problems:
        return None, problems

    status = row["status"].title()
    clean = {
        "transaction_id": row["transaction_id"],
        "order_date": order_date.isoformat(),
        "order_month": order_date.strftime("%Y-%m"),
        "product": row["product"],
        "category": row["category"],
        "region": row["region"],
        "sales_channel": row["sales_channel"],
        "quantity": quantity,
        "unit_price": unit_price,
        "discount_amount": discount,
        "status": status,
        "revenue": round(quantity * unit_price - discount, 2),
        "counts_toward_revenue": 1 if status == REVENUE_STATUS else 0,
    }
    return clean, []


def clean_rows(df: pd.DataFrame) -> CleaningResult:
    """Validate every row and separate accepted rows from rejected ones."""
    result = CleaningResult(rows_read=len(df))
    first_seen_line: dict = {}

    for index, raw in enumerate(df.to_dict("records")):
        source_row = index + 2  # line 1 of the file is the header
        clean, problems = validate_row(raw)

        if clean is not None:
            transaction_id = clean["transaction_id"]
            if transaction_id in first_seen_line:
                problems = [
                    f"duplicate transaction_id '{transaction_id}' "
                    f"(first imported from CSV line {first_seen_line[transaction_id]})"
                ]
                clean = None
            else:
                first_seen_line[transaction_id] = source_row

        if clean is None:
            result.rejected.append(
                RejectedRow(
                    source_row=source_row,
                    transaction_id=str(raw.get("transaction_id", "")).strip(),
                    reasons=problems,
                    raw={key: str(value) for key, value in raw.items()},
                )
            )
        else:
            result.accepted.append(clean)

    return result


def write_to_database(result: CleaningResult, db_path: Path) -> None:
    """Rebuild the tables in one transaction. Nothing changes if anything fails."""
    if not result.accepted:
        raise ValueError(
            "The CSV contains no valid rows, so nothing was loaded. "
            "The existing database (if any) was left unchanged."
        )

    conn = open_writable_connection(db_path)
    try:
        conn.execute("BEGIN")
        drop_schema(conn)
        create_schema(conn)
        conn.executemany(INSERT_SALES_SQL, result.accepted)
        conn.executemany(
            INSERT_REJECTED_SQL,
            [
                (
                    rejected.source_row,
                    rejected.transaction_id or None,
                    "; ".join(rejected.reasons),
                    json.dumps(rejected.raw),
                )
                for rejected in result.rejected
            ],
        )
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def verify_database(db_path: Path) -> tuple:
    """Return (rows in sales, rows in rejected_rows) as stored in SQLite."""
    conn = sqlite3.connect(db_path)
    try:
        sales_count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        rejected_count = conn.execute("SELECT COUNT(*) FROM rejected_rows").fetchone()[0]
    finally:
        conn.close()
    return sales_count, rejected_count


def print_report(result: CleaningResult, csv_path: Path, db_path: Path) -> None:
    accepted = result.accepted
    counted = [row for row in accepted if row["counts_toward_revenue"]]
    excluded = [row for row in accepted if not row["counts_toward_revenue"]]
    excluded_by_status = Counter(row["status"] for row in excluded)

    print("=" * 64)
    print("DATA LOAD REPORT")
    print("=" * 64)
    print(f"CSV file:      {csv_path}")
    print(f"Database file: {db_path}")
    print()
    print(f"Rows read from CSV:                          {result.rows_read}")
    print(f"Imported into 'sales':                       {len(accepted)}")
    print(f"Rejected (saved in 'rejected_rows'):         {len(result.rejected)}")
    print(f"Imported but excluded from revenue:          {len(excluded)}")
    for status, count in sorted(excluded_by_status.items()):
        print(f"    status '{status}': {count}")
    print(f"Imported rows counted toward revenue:        {len(counted)}")
    if accepted:
        dates = sorted(row["order_date"] for row in accepted)
        print(f"Date range of imported rows:                 {dates[0]} to {dates[-1]}")
    print(f"Revenue counted (Completed rows only):       {sum(r['revenue'] for r in counted):,.2f}")

    if result.rejected:
        print()
        print("Rejected rows:")
        for rejected in result.rejected[:MAX_REJECTED_PRINTED]:
            label = rejected.transaction_id or "no id"
            print(f"  CSV line {rejected.source_row} ({label}): {'; '.join(rejected.reasons)}")
        hidden = len(result.rejected) - MAX_REJECTED_PRINTED
        if hidden > 0:
            print(f"  and {hidden} more rejected rows (see the rejected_rows table)")
    print("=" * 64)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Load a sales CSV into SQLite.")
    parser.add_argument("--csv", default="data/sales.csv", help="CSV path (default: data/sales.csv)")
    parser.add_argument("--db", default=None, help="SQLite path (default: DATABASE_PATH or data/sales.db)")
    args = parser.parse_args(argv)

    csv_path = Path(args.csv).expanduser()
    if not csv_path.is_absolute():
        csv_path = BASE_DIR / csv_path
    db_path = Path(args.db).expanduser() if args.db else get_db_path()
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    try:
        df = read_csv(csv_path)
        result = clean_rows(df)
        write_to_database(result, db_path)
        print_report(result, csv_path, db_path)
        sales_count, rejected_count = verify_database(db_path)
        print(f"Verification: the database now holds {sales_count} sales rows "
              f"and {rejected_count} rejected rows.")
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except sqlite3.Error as exc:
        print(f"DATABASE ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())