"""Safe SQL analytics over the sales table."""

import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.schemas import QuerySpec

METRIC_SQL = {
    "revenue": "SUM(revenue)",
    "orders": "COUNT(*)",
    "units": "SUM(quantity)",
    "avg_order_value": "AVG(revenue)",
    "total_discount": "SUM(discount_amount)",
}
METRIC_LABELS = {
    "revenue": "Revenue",
    "orders": "Number of orders",
    "units": "Units sold",
    "avg_order_value": "Average order value",
    "total_discount": "Total discount",
}
GROUP_COLUMNS = {"product", "category", "region", "sales_channel", "order_month"}
FILTER_COLUMNS = {"product", "category", "region", "sales_channel"}


@dataclass
class QueryResult:
    rows: List[Tuple[str, float]]
    total: Optional[float]


def _round(value) -> Optional[float]:
    return None if value is None else round(float(value), 2)


def _where(spec: QuerySpec):
    clauses = ["counts_toward_revenue = 1"]
    params: list = []
    for column, value in spec.filters.items():
        if column not in FILTER_COLUMNS:
            raise ValueError(f"Filtering by '{column}' is not allowed.")
        clauses.append(f"{column} = ? COLLATE NOCASE")
        params.append(value)
    if spec.start_month:
        clauses.append("order_month >= ?")
        params.append(spec.start_month)
    if spec.end_month:
        clauses.append("order_month <= ?")
        params.append(spec.end_month)
    return " AND ".join(clauses), params


def run_query(conn: sqlite3.Connection, spec: QuerySpec) -> QueryResult:
    """Run a validated QuerySpec. `total` ignores group_by and limit."""
    where, params = _where(spec)
    expression = METRIC_SQL[spec.metric]

    total = _round(conn.execute(f"SELECT {expression} FROM sales WHERE {where}", params).fetchone()[0])
    if spec.group_by is None:
        return QueryResult(rows=[("Total", total)] if total is not None else [], total=total)

    column = spec.group_by
    if column not in GROUP_COLUMNS:
        raise ValueError(f"Grouping by '{column}' is not allowed.")
    # Months read best in time order; everything else is sorted by the metric.
    order = f"{column} ASC" if column == "order_month" else f"metric_value {spec.sort.upper()}, {column} ASC"
    sql = (
        f"SELECT {column} AS label, {expression} AS metric_value "
        f"FROM sales WHERE {where} GROUP BY {column} ORDER BY {order}"
    )
    query_params = list(params)
    if spec.limit:
        sql += " LIMIT ?"
        query_params.append(spec.limit)

    rows = [(str(r[0]), _round(r[1])) for r in conn.execute(sql, query_params).fetchall()]
    return QueryResult(rows=rows, total=total)


def get_known_values(conn: sqlite3.Connection) -> Dict[str, List[str]]:
    """Distinct values per dimension, used to understand questions."""
    known: Dict[str, List[str]] = {}
    for column in sorted(GROUP_COLUMNS):
        rows = conn.execute(f"SELECT DISTINCT {column} FROM sales ORDER BY {column}").fetchall()
        known[column] = [row[0] for row in rows]
    return known


def describe_spec(spec: QuerySpec) -> str:
    """Plain-English description of what was calculated."""
    text = METRIC_LABELS[spec.metric]
    if spec.group_by:
        text += f" by {spec.group_by.replace('_', ' ')}"
    parts = [f"{k.replace('_', ' ')} = {v}" for k, v in spec.filters.items()]
    if spec.start_month and spec.start_month == spec.end_month:
        parts.append(f"month = {spec.start_month}")
    elif spec.start_month or spec.end_month:
        parts.append(f"months {spec.start_month or 'start'} to {spec.end_month or 'end'}")
    if parts:
        text += " (" + ", ".join(parts) + ")"
    if spec.limit:
        text += f", {'top' if spec.sort == 'desc' else 'bottom'} {spec.limit}"
    return text + ". Completed orders only."