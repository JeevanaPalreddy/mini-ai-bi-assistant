from app.analytics import get_known_values, run_query
from app.database import get_readonly_connection
from app.schemas import QuerySpec
from load_data import verify_database


def test_loader_counts(db_path):
    assert verify_database(db_path) == (5, 1)  # 5 imported (1 Returned), 1 rejected


def test_total_revenue_completed_only(db_path):
    with get_readonly_connection() as conn:
        assert run_query(conn, QuerySpec(metric="revenue")).total == 3240.0


def test_orders_and_units(db_path):
    with get_readonly_connection() as conn:
        assert run_query(conn, QuerySpec(metric="orders")).total == 4
        assert run_query(conn, QuerySpec(metric="units")).total == 16


def test_group_by_region(db_path):
    with get_readonly_connection() as conn:
        rows = dict(run_query(conn, QuerySpec(group_by="region")).rows)
    assert rows == {"North": 2040.0, "South": 1200.0}


def test_filter_is_case_insensitive(db_path):
    with get_readonly_connection() as conn:
        spec = QuerySpec(filters={"region": "north"})
        assert run_query(conn, spec).total == 2040.0


def test_month_range_and_swapped_months(db_path):
    with get_readonly_connection() as conn:
        spec = QuerySpec(start_month="2026-02", end_month="2026-01")  # auto-swapped
        assert run_query(conn, spec).total == 3100.0


def test_limit(db_path):
    with get_readonly_connection() as conn:
        rows = run_query(conn, QuerySpec(group_by="product", limit=1)).rows
    assert rows == [("Laptop", 2900.0)]


def test_known_values(db_path):
    with get_readonly_connection() as conn:
        assert get_known_values(conn)["region"] == ["North", "South"]