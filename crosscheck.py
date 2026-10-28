"""Compare SQL analytics against an independent pandas calculation from the raw CSV."""

import sys

import pandas as pd

from app.analytics import run_query
from app.database import get_readonly_connection
from app.schemas import QuerySpec

df = pd.read_csv("data/sales.csv")
df.columns = [c.strip().lower() for c in df.columns]
for col in ("product", "category", "region", "sales_channel", "status"):
    df[col] = df[col].astype(str).str.strip()
for col in ("quantity", "unit_price", "discount_amount"):
    df[col] = pd.to_numeric(df[col], errors="coerce")
df["order_date"] = pd.to_datetime(df["order_date"], format="%d-%m-%Y", errors="coerce")

df = df[df["status"].str.title() == "Completed"]
df = df.dropna(subset=["quantity", "unit_price", "discount_amount", "order_date"])
df = df[df["quantity"] > 0]
df["revenue"] = df["quantity"] * df["unit_price"] - df["discount_amount"]
df["order_month"] = df["order_date"].dt.strftime("%Y-%m")

failures = 0


def check(label, expected, actual):
    global failures
    ok = expected is not None and actual is not None and abs(expected - actual) < 0.01
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}: pandas={expected} sql={actual}")


with get_readonly_connection() as conn:
    check("Total revenue", round(df["revenue"].sum(), 2), run_query(conn, QuerySpec(metric="revenue")).total)
    check("Completed orders", len(df), run_query(conn, QuerySpec(metric="orders")).total)
    check("Units sold", df["quantity"].sum(), run_query(conn, QuerySpec(metric="units")).total)

    for dim in ("region", "product", "category", "sales_channel", "order_month"):
        sql_rows = dict(run_query(conn, QuerySpec(metric="revenue", group_by=dim)).rows)
        expected = df.groupby(dim)["revenue"].sum().round(2).to_dict()
        same_groups = set(sql_rows) == set(expected)
        worst = max((abs(expected[k] - sql_rows[k]) for k in expected if k in sql_rows), default=0)
        ok = same_groups and worst < 0.01
        failures += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  Revenue by {dim}: {len(expected)} groups, largest difference {worst:.2f}")

print("\nALL CHECKS PASSED" if failures == 0 else f"\n{failures} CHECK(S) FAILED")
sys.exit(1 if failures else 0)