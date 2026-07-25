import json
import sqlite3

import pytest

from app.build import build_redacted, main


def _make_full_db(path, rows, last_updated="2026-07-25T00:00:00+00:00"):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE products (product_name TEXT, secret_field TEXT, last_updated TEXT)"
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, ?)",
        [(name, secret, last_updated) for name, secret in rows],
    )
    conn.commit()
    conn.close()
    return last_updated


def _approve(tmp_path, anchor):
    approved_path = tmp_path / "products.approved"
    approved_path.write_text(anchor)
    return approved_path


def test_build_redacted_removes_sensitive_fields(tmp_path):
    full_db = tmp_path / "full.db"
    anchor = _make_full_db(full_db, [("Box", "hidden")])

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps(["secret_field"]))
    approved_path = _approve(tmp_path, anchor)

    redacted_db = tmp_path / "redacted.db"
    build_redacted(str(full_db), str(redacted_db), str(fields_path), str(approved_path))

    conn = sqlite3.connect(str(redacted_db))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(products)")]
    rows = conn.execute("SELECT product_name FROM products").fetchall()
    conn.close()

    assert columns == ["product_name", "last_updated"]
    assert rows == [("Box",)]


def test_build_redacted_is_idempotent(tmp_path):
    full_db = tmp_path / "full.db"
    anchor = _make_full_db(full_db, [("Box", "hidden")])

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps(["secret_field"]))
    approved_path = _approve(tmp_path, anchor)

    redacted_db = tmp_path / "redacted.db"
    build_redacted(str(full_db), str(redacted_db), str(fields_path), str(approved_path))
    build_redacted(str(full_db), str(redacted_db), str(fields_path), str(approved_path))

    conn = sqlite3.connect(str(redacted_db))
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()

    assert count == 1


def test_build_redacted_refuses_without_approval(tmp_path):
    full_db = tmp_path / "full.db"
    _make_full_db(full_db, [("Box", "hidden")])

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps(["secret_field"]))
    missing_approved_path = tmp_path / "products.approved"

    redacted_db = tmp_path / "redacted.db"
    with pytest.raises(SystemExit):
        build_redacted(str(full_db), str(redacted_db), str(fields_path), str(missing_approved_path))


def test_build_redacted_refuses_on_stale_approval(tmp_path):
    full_db = tmp_path / "full.db"
    _make_full_db(full_db, [("Box", "hidden")])

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps(["secret_field"]))
    approved_path = _approve(tmp_path, "an-old-anchor-that-does-not-match")

    redacted_db = tmp_path / "redacted.db"
    with pytest.raises(SystemExit):
        build_redacted(str(full_db), str(redacted_db), str(fields_path), str(approved_path))


def test_main_writes_to_conventional_default_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    anchor = _make_full_db(tmp_path / "data" / "products.db", [("Box", "hidden")])
    (tmp_path / "sensitive_fields.json").write_text(json.dumps(["secret_field"]))
    (tmp_path / "data" / "products.approved").write_text(anchor)

    main([])

    conn = sqlite3.connect(str(tmp_path / "data" / "products_public.db"))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(products)")]
    conn.close()

    assert columns == ["product_name", "last_updated"]
