import json
import sqlite3

from app.build import build_redacted, main


def _make_full_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE products (product_name TEXT, secret_field TEXT)")
    conn.executemany("INSERT INTO products VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def test_build_redacted_removes_sensitive_fields(tmp_path):
    full_db = tmp_path / "full.db"
    _make_full_db(full_db, [("Box", "hidden")])

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps(["secret_field"]))

    redacted_db = tmp_path / "redacted.db"
    build_redacted(str(full_db), str(redacted_db), str(fields_path))

    conn = sqlite3.connect(str(redacted_db))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(products)")]
    rows = conn.execute("SELECT * FROM products").fetchall()
    conn.close()

    assert columns == ["product_name"]
    assert rows == [("Box",)]


def test_build_redacted_is_idempotent(tmp_path):
    full_db = tmp_path / "full.db"
    _make_full_db(full_db, [("Box", "hidden")])

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps(["secret_field"]))

    redacted_db = tmp_path / "redacted.db"
    build_redacted(str(full_db), str(redacted_db), str(fields_path))
    build_redacted(str(full_db), str(redacted_db), str(fields_path))

    conn = sqlite3.connect(str(redacted_db))
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()

    assert count == 1


def test_main_writes_to_conventional_default_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _make_full_db(tmp_path / "data" / "products.db", [("Box", "hidden")])
    (tmp_path / "sensitive_fields.json").write_text(json.dumps(["secret_field"]))

    main([])

    conn = sqlite3.connect(str(tmp_path / "data" / "products_public.db"))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(products)")]
    conn.close()

    assert columns == ["product_name"]
