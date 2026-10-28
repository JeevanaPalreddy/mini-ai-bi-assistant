from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health(db_path):
    assert client.get("/health").json() == {"status": "ok", "database_ready": True}


def test_ask_total_revenue(db_path):
    r = client.post("/ask", json={"question": "Total revenue"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3240.0
    assert body["interpreted_by"] == "rule_based_fallback"


def test_ask_grouped(db_path):
    r = client.post("/ask", json={"question": "Revenue by region"})
    assert {row["label"] for row in r.json()["rows"]} == {"North", "South"}


def test_empty_question_rejected(db_path):
    assert client.post("/ask", json={"question": "   "}).status_code == 422


def test_too_long_question_rejected(db_path):
    assert client.post("/ask", json={"question": "x" * 501}).status_code == 422


def test_sql_injection_is_harmless(db_path):
    r = client.post("/ask", json={"question": "'; DROP TABLE sales; --"})
    assert r.status_code == 200
    assert client.post("/ask", json={"question": "Total revenue"}).json()["total"] == 3240.0


def test_missing_database_returns_503(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "nope.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert client.get("/health").json()["database_ready"] is False
    assert client.post("/ask", json={"question": "Total revenue"}).status_code == 503