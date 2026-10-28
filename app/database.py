"""SQLite schema and connection helpers.

- The loader uses open_writable_connection() to rebuild the tables.
- The API uses get_readonly_connection(), which cannot modify the database.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = "data/sales.db"


class DatabaseUnavailableError(Exception):
    """Raised when the SQLite database is missing or cannot be opened."""


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE sales (
        transaction_id        TEXT PRIMARY KEY,
        order_date            TEXT NOT NULL,   -- ISO format: YYYY-MM-DD
        order_month           TEXT NOT NULL,   -- YYYY-MM
        product               TEXT NOT NULL,
        category              TEXT NOT NULL,
        region                TEXT NOT NULL,
        sales_channel         TEXT NOT NULL,
        quantity              INTEGER NOT NULL,
        unit_price            REAL NOT NULL,
        discount_amount       REAL NOT NULL,
        status                TEXT NOT NULL,
        revenue               REAL NOT NULL,   -- quantity * unit_price - discount_amount
        counts_toward_revenue INTEGER NOT NULL -- 1 only when status is 'Completed'
    )
    """,
    "CREATE INDEX idx_sales_month ON sales (order_month)",
    "CREATE INDEX idx_sales_product ON sales (product)",
    "CREATE INDEX idx_sales_region ON sales (region)",
    """
    CREATE TABLE rejected_rows (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        source_row     INTEGER NOT NULL,  -- line number in the CSV (header is line 1)
        transaction_id TEXT,
        reason         TEXT NOT NULL,
        raw_values     TEXT NOT NULL      -- the original row as JSON
    )
    """,
)


def get_db_path() -> Path:
    """Return the database path from DATABASE_PATH (default: data/sales.db)."""
    path = Path(os.getenv("DATABASE_PATH", DEFAULT_DB_PATH)).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def drop_schema(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS sales")
    conn.execute("DROP TABLE IF EXISTS rejected_rows")


def create_schema(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)


def open_writable_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a read-write connection for the loader.

    isolation_level=None means we control transactions ourselves
    (explicit BEGIN / COMMIT / ROLLBACK), so a failed load changes nothing.
    """
    path = Path(db_path) if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.isolation_level = None
    return conn


@contextmanager
def get_readonly_connection(
    db_path: Optional[Path] = None,
) -> Iterator[sqlite3.Connection]:
    """Yield a read-only connection and always close it afterwards."""
    path = Path(db_path) if db_path else get_db_path()
    if not path.is_file():
        raise DatabaseUnavailableError(
            f"Database file '{path.name}' was not found. Run load_data.py first."
        )
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
    except sqlite3.Error as exc:
        raise DatabaseUnavailableError("The database could not be opened.") from exc
    try:
        yield conn
    finally:
        conn.close()


def database_is_ready(db_path: Optional[Path] = None) -> bool:
    """True if the database file exists and the sales table can be queried."""
    try:
        with get_readonly_connection(db_path) as conn:
            conn.execute("SELECT COUNT(*) FROM sales").fetchone()
        return True
    except (DatabaseUnavailableError, sqlite3.Error):
        return False