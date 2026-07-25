import json
import sqlite3

from app.sync_sheets import build_rows, sync_to_sheet


def _make_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE products_merged (product_name TEXT, value_total TEXT)")
    conn.executemany("INSERT INTO products_merged VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def test_build_rows_includes_header(tmp_path):
    db = tmp_path / "products.db"
    _make_db(db, [("Box", "10"), ("Pack", None)])

    rows = build_rows(str(db), "products_merged")

    assert rows[0] == ["product_name", "value_total"]
    assert rows[1] == ["Box", "10"]
    assert rows[2] == ["Pack", ""]


def test_sync_to_sheet_clears_before_updating(monkeypatch):
    """Per ADR-14: clear-then-update, not append -- a second run with the
    same data must not duplicate rows, so clear must run first."""
    calls = []
    monkeypatch.setattr(
        "app.sync_sheets.subprocess.run",
        lambda args, check: calls.append(args),
    )

    sync_to_sheet("SHEET_ID", [["product_name"], ["Box"]], "Sheet1")

    assert len(calls) == 2
    assert calls[0][:5] == ["gws", "sheets", "spreadsheets", "values", "clear"]
    assert calls[1][:5] == ["gws", "sheets", "spreadsheets", "values", "update"]
    update_json = json.loads(calls[1][calls[1].index("--json") + 1])
    assert update_json == {"values": [["product_name"], ["Box"]]}
