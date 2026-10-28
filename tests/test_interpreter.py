import pytest

from app import interpreter
from app.analytics import get_known_values
from app.database import get_readonly_connection


@pytest.fixture
def known(db_path):
    with get_readonly_connection() as conn:
        return get_known_values(conn)


def test_top_products(known):
    spec = interpreter.interpret_with_rules("Top 2 products by revenue", known)
    assert spec.group_by == "product" and spec.limit == 2 and spec.sort == "desc"


def test_monthly_trend(known):
    spec = interpreter.interpret_with_rules("Monthly revenue trend", known)
    assert spec.group_by == "order_month"


def test_filter_and_metric(known):
    spec = interpreter.interpret_with_rules("How many orders in North?", known)
    assert spec.metric == "orders" and spec.filters == {"region": "North"}


def test_no_key_uses_fallback(known):
    result = interpreter.interpret("Total revenue", known)
    assert result.source == "rule_based_fallback" and result.notice


def test_llm_failure_falls_back(known, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    def boom(question, known):
        raise RuntimeError("down")

    monkeypatch.setattr(interpreter, "interpret_with_llm", boom)
    result = interpreter.interpret("Total revenue", known)
    assert result.source == "rule_based_fallback" and "RuntimeError" in result.notice


def test_unknown_llm_filter_rejected(known):
    from app.schemas import QuerySpec

    with pytest.raises(ValueError):
        interpreter._canonical_filters(QuerySpec(filters={"region": "Mars"}), known)