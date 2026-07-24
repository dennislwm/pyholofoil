import sqlite3

from datasette_saved_queries import create_tables


def test_saved_queries_table_creation_is_idempotent(tmp_path):
    """Per ADR-07: datasette-saved-queries creates a saved_queries table in
    products.db on every Datasette startup. Calling its own create_tables()
    twice against the same file (simulating two `make explore` runs) must
    not error or duplicate the table."""
    db_path = tmp_path / "products.db"
    conn = sqlite3.connect(str(db_path))

    create_tables(conn)
    create_tables(conn)

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='saved_queries'"
    ).fetchall()
    conn.close()

    assert tables == [("saved_queries",)]
