import pytest

from load_data import main as load_main

CSV = """Transaction_Id,Order_Date,Product,Category,Region,Sales_Channel,Quantity,Unit_Price,Discount_Amount,Status
TXN1,05-01-2026,Laptop,Electronics,North,Online,2,1000,100,Completed
TXN2,10-01-2026,Mouse,Accessories,South,Store,10,20,0,Completed
TXN3,15-02-2026,Laptop,Electronics,South,Online,1,1000,0,Completed
TXN4,20-02-2026,Mouse,Accessories,North,Store,5,20,0,Returned
TXN5,25-02-2026,Laptop,Electronics,North,Online,0,1000,0,Completed
TXN6,03-03-2026,Keyboard,Accessories,North,Online,3,50,10,Completed
"""


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    csv = tmp_path / "sales.csv"
    csv.write_text(CSV)
    db = tmp_path / "test.db"
    assert load_main(["--csv", str(csv), "--db", str(db)]) == 0
    monkeypatch.setenv("DATABASE_PATH", str(db))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    return db