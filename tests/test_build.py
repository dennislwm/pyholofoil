import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app.build import build_redacted, main, publish_static, verify_redacted


def _make_full_db(path, rows, last_updated="2026-07-25T00:00:00+00:00"):
    """rarity defaults to 'Sealed' for every row -- per REQ-032,
    build_redacted() only keeps Sealed rows, and these fixtures test
    unrelated behavior (column redaction, idempotency), not row filtering."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE products (product_name TEXT, secret_field TEXT, rarity TEXT, last_updated TEXT)"
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, ?, ?)",
        [(name, secret, "Sealed", last_updated) for name, secret in rows],
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
    build_redacted(str(full_db), str(redacted_db), str(fields_path), str(approved_path), "products")

    conn = sqlite3.connect(str(redacted_db))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(products)")]
    rows = conn.execute("SELECT product_name FROM products").fetchall()
    conn.close()

    assert columns == ["product_name", "rarity", "last_updated"]
    assert rows == [("Box",)]


def test_build_redacted_is_idempotent(tmp_path):
    full_db = tmp_path / "full.db"
    anchor = _make_full_db(full_db, [("Box", "hidden")])

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps(["secret_field"]))
    approved_path = _approve(tmp_path, anchor)

    redacted_db = tmp_path / "redacted.db"
    build_redacted(str(full_db), str(redacted_db), str(fields_path), str(approved_path), "products")
    build_redacted(str(full_db), str(redacted_db), str(fields_path), str(approved_path), "products")

    conn = sqlite3.connect(str(redacted_db))
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()

    assert count == 1


def test_approve_makefile_target_is_idempotent(tmp_path):
    """Runs the real `make approve` target (not a Python reimplementation of
    its redirect) against a fixture db, twice, so a regression of the
    Makefile's `>` to `>>` would break this test."""
    full_db = tmp_path / "full.db"
    anchor = _make_full_db(full_db, [("Box", "hidden")])

    (tmp_path / "data").mkdir()
    approved_path = tmp_path / "data" / "products.approved"
    makefile_path = Path(__file__).parent.parent / "Makefile"

    def run_approve():
        subprocess.run(
            ["make", "-f", str(makefile_path), "approve", f"DB_PATH={full_db}"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    run_approve()
    run_approve()

    assert approved_path.read_text().strip() == anchor


def test_build_redacted_refuses_without_approval(tmp_path):
    full_db = tmp_path / "full.db"
    _make_full_db(full_db, [("Box", "hidden")])

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps(["secret_field"]))
    missing_approved_path = tmp_path / "products.approved"

    redacted_db = tmp_path / "redacted.db"
    with pytest.raises(SystemExit):
        build_redacted(
            str(full_db), str(redacted_db), str(fields_path), str(missing_approved_path), "products"
        )


def test_build_redacted_refuses_on_stale_approval(tmp_path):
    full_db = tmp_path / "full.db"
    _make_full_db(full_db, [("Box", "hidden")])

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps(["secret_field"]))
    approved_path = _approve(tmp_path, "an-old-anchor-that-does-not-match")

    redacted_db = tmp_path / "redacted.db"
    with pytest.raises(SystemExit):
        build_redacted(str(full_db), str(redacted_db), str(fields_path), str(approved_path), "products")


def test_main_writes_to_conventional_default_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "products.db"
    anchor = _make_full_db(db_path, [("Box", "hidden")])
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE VIEW products_merged AS SELECT * FROM products")
    conn.commit()
    conn.close()
    (tmp_path / "redaction.yaml").write_text("_global:\n  - secret_field\n")
    (tmp_path / "data" / "products.approved").write_text(anchor)

    main([])

    conn = sqlite3.connect(str(tmp_path / "data" / "products_public.db"))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(products)")]
    conn.close()

    assert columns == ["product_name", "rarity", "last_updated"]


def test_build_redacted_keeps_only_sealed_rarity_rows(tmp_path):
    """Per REQ-032: a "rows" WHERE fragment declared under "_global" in
    sensitive_fields.yaml filters which rows reach the public/redacted
    artifact -- confirmed live against real sample data (117/315 rows had
    rarity == "Sealed" in input/ShinyExport-20260528.json)."""
    full_db = tmp_path / "full.db"
    conn = sqlite3.connect(str(full_db))
    conn.execute(
        "CREATE TABLE products (product_name TEXT, rarity TEXT, last_updated TEXT)"
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, ?)",
        [
            ("Sealed Box", "Sealed", "2026-07-25T00:00:00+00:00"),
            ("Loose Card", "Common", "2026-07-25T00:00:00+00:00"),
        ],
    )
    conn.commit()
    conn.close()
    anchor = "2026-07-25T00:00:00+00:00"

    fields_path = tmp_path / "sensitive_fields.yaml"
    fields_path.write_text("_global:\n  rows: \"rarity = 'Sealed'\"\n")
    approved_path = _approve(tmp_path, anchor)

    redacted_db = tmp_path / "redacted.db"
    build_redacted(str(full_db), str(redacted_db), str(fields_path), str(approved_path), "products")

    conn = sqlite3.connect(str(redacted_db))
    rows = conn.execute("SELECT product_name FROM products").fetchall()
    conn.close()

    assert rows == [("Sealed Box",)]


def test_build_redacted_no_row_filter_configured_keeps_every_row(tmp_path):
    """Per REQ-032: omitting "rows" from sensitive_fields.yaml (the old
    flat/bare-list shape, or a dict with no "rows" key) keeps every row --
    zero declared row filters means zero behavior change."""
    full_db = tmp_path / "full.db"
    conn = sqlite3.connect(str(full_db))
    conn.execute(
        "CREATE TABLE products (product_name TEXT, rarity TEXT, last_updated TEXT)"
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, ?)",
        [
            ("Sealed Box", "Sealed", "2026-07-25T00:00:00+00:00"),
            ("Loose Card", "Common", "2026-07-25T00:00:00+00:00"),
        ],
    )
    conn.commit()
    conn.close()
    anchor = "2026-07-25T00:00:00+00:00"

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps([]))
    approved_path = _approve(tmp_path, anchor)

    redacted_db = tmp_path / "redacted.db"
    build_redacted(str(full_db), str(redacted_db), str(fields_path), str(approved_path), "products")

    conn = sqlite3.connect(str(redacted_db))
    rows = conn.execute("SELECT product_name FROM products").fetchall()
    conn.close()

    assert len(rows) == 2


def test_build_redacted_global_and_per_table_row_filters_combine(tmp_path):
    """Per REQ-032: a "_global" rows fragment and a per-table rows fragment
    both apply (combined via AND) when both are declared."""
    full_db = tmp_path / "full.db"
    conn = sqlite3.connect(str(full_db))
    conn.execute(
        "CREATE TABLE products (product_name TEXT, rarity TEXT, quantity INTEGER, last_updated TEXT)"
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, ?, ?)",
        [
            ("Sealed Box A", "Sealed", 1, "2026-07-25T00:00:00+00:00"),
            ("Sealed Box B", "Sealed", 0, "2026-07-25T00:00:00+00:00"),
            ("Loose Card", "Common", 1, "2026-07-25T00:00:00+00:00"),
        ],
    )
    conn.commit()
    conn.close()
    anchor = "2026-07-25T00:00:00+00:00"

    fields_path = tmp_path / "sensitive_fields.yaml"
    fields_path.write_text(
        "_global:\n"
        "  rows: \"rarity = 'Sealed'\"\n"
        "products:\n"
        "  rows: \"quantity > 0\"\n"
    )
    approved_path = _approve(tmp_path, anchor)

    redacted_db = tmp_path / "redacted.db"
    build_redacted(str(full_db), str(redacted_db), str(fields_path), str(approved_path), "products")

    conn = sqlite3.connect(str(redacted_db))
    rows = conn.execute("SELECT product_name FROM products").fetchall()
    conn.close()

    assert rows == [("Sealed Box A",)]


def test_build_redacted_default_source_table_includes_overrides(tmp_path):
    """Per REQ-012: default source_table (products_merged) surfaces
    operator corrections that build_redacted() previously could never see
    when hardcoded to products."""
    full_db = tmp_path / "full.db"
    anchor = _make_full_db(full_db, [("Box", "hidden")])
    conn = sqlite3.connect(str(full_db))
    conn.execute(
        "CREATE VIEW products_merged AS "
        "SELECT 'Corrected Box' AS product_name, secret_field, rarity, last_updated FROM products"
    )
    conn.commit()
    conn.close()

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps(["secret_field"]))
    approved_path = _approve(tmp_path, anchor)

    redacted_db = tmp_path / "redacted.db"
    build_redacted(
        str(full_db), str(redacted_db), str(fields_path), str(approved_path), "products_merged"
    )

    conn = sqlite3.connect(str(redacted_db))
    rows = conn.execute("SELECT product_name FROM products").fetchall()
    conn.close()

    assert rows == [("Corrected Box",)]


def test_build_redacted_per_table_fields_dont_leak_across_tables(tmp_path):
    """Per ADR-27: a column listed under one table's key must not be
    redacted for a different table that doesn't list it."""
    full_db = tmp_path / "full.db"
    anchor = _make_full_db(full_db, [("Box", "hidden")])
    conn = sqlite3.connect(str(full_db))
    conn.execute("CREATE VIEW products_merged_sold AS SELECT * FROM products")
    conn.commit()
    conn.close()

    fields_path = tmp_path / "sensitive_fields.yaml"
    fields_path.write_text("_global: []\nproducts_merged_sold:\n  - secret_field\n")
    approved_path = _approve(tmp_path, anchor)

    redacted_db = tmp_path / "redacted.db"
    build_redacted(
        str(full_db), str(redacted_db), str(fields_path), str(approved_path), "products"
    )
    conn = sqlite3.connect(str(redacted_db))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(products)")]
    conn.close()

    assert "secret_field" in columns


def test_build_redacted_global_and_per_table_fields_combine(tmp_path):
    """Per ADR-27: _global applies to every table in addition to that
    table's own key."""
    full_db = tmp_path / "full.db"
    anchor = _make_full_db(full_db, [("Box", "hidden")])
    conn = sqlite3.connect(str(full_db))
    conn.execute(
        "CREATE VIEW products_merged_sold AS "
        "SELECT product_name, secret_field, rarity, 'extra' AS sold_value_total, last_updated FROM products"
    )
    conn.commit()
    conn.close()

    fields_path = tmp_path / "sensitive_fields.yaml"
    fields_path.write_text(
        "_global:\n  - secret_field\nproducts_merged_sold:\n  - sold_value_total\n"
    )
    approved_path = _approve(tmp_path, anchor)

    redacted_db = tmp_path / "redacted.db"
    build_redacted(
        str(full_db), str(redacted_db), str(fields_path), str(approved_path), "products_merged_sold"
    )
    conn = sqlite3.connect(str(redacted_db))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(products)")]
    conn.close()

    assert columns == ["product_name", "rarity", "last_updated"]


def test_verify_redacted_passes_on_clean_artifact(tmp_path):
    redacted_db = tmp_path / "redacted.db"
    conn = sqlite3.connect(str(redacted_db))
    conn.execute("CREATE TABLE products (product_name TEXT)")
    conn.commit()
    conn.close()

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps(["secret_field"]))

    verify_redacted(str(redacted_db), str(fields_path))


def test_verify_redacted_refuses_leaked_sensitive_field(tmp_path):
    """Per REQ-013: deploy must refuse to publish an artifact that still
    contains a sensitive column -- e.g. a stale REDACTED_DB_PATH override
    pointed straight at the unredacted full db, which nothing caught
    before this check existed."""
    redacted_db = tmp_path / "redacted.db"
    conn = sqlite3.connect(str(redacted_db))
    conn.execute("CREATE TABLE products (product_name TEXT, secret_field TEXT)")
    conn.commit()
    conn.close()

    fields_path = tmp_path / "sensitive_fields.json"
    fields_path.write_text(json.dumps(["secret_field"]))

    with pytest.raises(SystemExit):
        verify_redacted(str(redacted_db), str(fields_path))


def test_verify_redacted_catches_leak_from_any_declared_table(tmp_path):
    """Per ADR-27: verify_redacted() isn't told which source_table built the
    artifact, so it must catch a leak of a column declared sensitive under
    ANY table's key, not just _global."""
    redacted_db = tmp_path / "redacted.db"
    conn = sqlite3.connect(str(redacted_db))
    conn.execute("CREATE TABLE products (product_name TEXT, sold_value_total TEXT)")
    conn.commit()
    conn.close()

    fields_path = tmp_path / "sensitive_fields.yaml"
    fields_path.write_text(
        "_global: []\nproducts_merged_sold:\n  - sold_value_total\n"
    )

    with pytest.raises(SystemExit):
        verify_redacted(str(redacted_db), str(fields_path))


def test_verify_redacted_catches_leak_with_dict_shaped_entries(tmp_path):
    """Per REQ-032: an entry can now be a dict ({columns: [...], rows: "..."})
    instead of a bare list -- verify_redacted() must still extract the
    columns correctly, not iterate the dict's own keys ("columns"/"rows")
    as if they were column names."""
    redacted_db = tmp_path / "redacted.db"
    conn = sqlite3.connect(str(redacted_db))
    conn.execute("CREATE TABLE products (product_name TEXT, paid_total TEXT)")
    conn.commit()
    conn.close()

    fields_path = tmp_path / "sensitive_fields.yaml"
    fields_path.write_text(
        "_global:\n  columns:\n    - paid_total\n  rows: \"rarity = 'Sealed'\"\n"
    )

    with pytest.raises(SystemExit):
        verify_redacted(str(redacted_db), str(fields_path))


def test_verify_redacted_passes_clean_artifact_with_dict_shaped_entries(tmp_path):
    """Companion to the above: a dict-shaped entry with no actual leak must
    not false-positive on the dict's own "columns"/"rows" keys."""
    redacted_db = tmp_path / "redacted.db"
    conn = sqlite3.connect(str(redacted_db))
    conn.execute("CREATE TABLE products (product_name TEXT)")
    conn.commit()
    conn.close()

    fields_path = tmp_path / "sensitive_fields.yaml"
    fields_path.write_text(
        "_global:\n  columns:\n    - paid_total\n  rows: \"rarity = 'Sealed'\"\n"
    )

    verify_redacted(str(redacted_db), str(fields_path))


def test_publish_static_copies_into_docs_dir(tmp_path):
    """Per ADR-16: the public copy is served as a static file (datasette-lite
    loads it directly), so deploy just needs a plain copy into the static
    host's serving directory (e.g. GitHub Pages' docs/)."""
    redacted_db = tmp_path / "redacted.db"
    redacted_db.write_bytes(b"fake sqlite bytes")
    docs_dir = tmp_path / "docs"

    dest = publish_static(str(redacted_db), str(docs_dir))

    assert dest == str(docs_dir / "products_public.db")
    assert (docs_dir / "products_public.db").read_bytes() == b"fake sqlite bytes"


def test_publish_static_is_idempotent(tmp_path):
    """Re-running deploy on the same artifact must not duplicate or corrupt
    the published copy -- a second copy overwrites cleanly."""
    redacted_db = tmp_path / "redacted.db"
    redacted_db.write_bytes(b"version one")
    docs_dir = tmp_path / "docs"

    publish_static(str(redacted_db), str(docs_dir))
    redacted_db.write_bytes(b"version two")
    publish_static(str(redacted_db), str(docs_dir))

    assert (docs_dir / "products_public.db").read_bytes() == b"version two"
    assert list(docs_dir.iterdir()) == [docs_dir / "products_public.db"]
