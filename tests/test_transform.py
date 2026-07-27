import json
import sqlite3

import pytest

from app.transform import load_products, main


def test_load_products_creates_one_flat_table(tmp_path):
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([
        {
            "id": "aaa",
            "product_name": "151 Booster Box Case",
            "set_name": "Pokémon Card 151",
            "brand_name": "Pokemon",
            "rarity": "Sealed",
            "tcgplayer_id": "null",
        },
        {
            "id": "bbb",
            "product_name": "151 Booster Bundle",
            "set_name": "Scarlet & Violet 151",
            "brand_name": "Pokemon",
            "rarity": "Sealed",
            "tcgplayer_id": "502000",
        },
    ]))
    db_path = tmp_path / "pyholofoil.db"

    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT product_name, set_name, rarity FROM products ORDER BY product_name"
    ).fetchall()
    conn.close()

    assert rows == [
        ("151 Booster Box Case", "Pokémon Card 151", "Sealed"),
        ("151 Booster Bundle", "Scarlet & Violet 151", "Sealed"),
    ]


def test_load_products_is_idempotent_on_same_file(tmp_path):
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([
        {"id": "aaa", "product_name": "151 Booster Box Case", "set_name": "Pokémon Card 151"},
    ]))
    db_path = tmp_path / "pyholofoil.db"

    load_products(str(json_path), str(db_path))
    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()

    assert count == 1


def test_load_products_updates_in_place_when_fields_change(tmp_path):
    json_path = tmp_path / "shiny.json"
    db_path = tmp_path / "pyholofoil.db"

    json_path.write_text(json.dumps([
        {"id": "aaa", "product_name": "Miscellaneous Pokemon", "set_name": "X"},
    ]))
    load_products(str(json_path), str(db_path))

    json_path.write_text(json.dumps([
        {"id": "aaa", "product_name": "ME Black Star Promos", "set_name": "X"},
    ]))
    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT product_name FROM products").fetchall()
    conn.close()

    assert rows == [("ME Black Star Promos",)]


def test_load_products_sets_last_updated_on_write(tmp_path):
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([
        {"id": "aaa", "product_name": "151 Booster Box Case", "set_name": "Pokémon Card 151"},
    ]))
    db_path = tmp_path / "pyholofoil.db"

    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    last_updated = conn.execute("SELECT last_updated FROM products").fetchone()[0]
    conn.close()

    assert last_updated is not None


def test_load_products_against_pre_adr06_schema_table_fails_clearly(tmp_path):
    """Per ADR-08: a products.db left over from before ADR-06 still has the
    old snapshot_date-keyed schema (no last_updated column, no PRIMARY
    KEY(id)). _check_schema() generically detects this mismatch and raises
    SystemExit with a rename-based recovery instruction, instead of letting
    a raw sqlite3.OperationalError surface."""
    db_path = tmp_path / "products.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE products (id TEXT, product_name TEXT, set_name TEXT, "
        "brand_name TEXT, discriminator TEXT, rarity TEXT, quantity TEXT, "
        "value_total TEXT, value_per_unit TEXT, value_currency TEXT, "
        "paid_total TEXT, paid_per_unit TEXT, paid_currency TEXT, "
        "grade_type TEXT, grade_subtype TEXT, group_name TEXT, "
        "group_wishlist TEXT, tcgplayer_id TEXT, pricecharting_id TEXT, "
        "doubleholo_id TEXT, date_added TEXT, tag TEXT, snapshot_date TEXT)"
    )
    conn.commit()
    conn.close()

    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    with pytest.raises(SystemExit, match="stale"):
        load_products(str(json_path), str(db_path))


def test_load_products_accepts_csv(tmp_path):
    csv_path = tmp_path / "shiny.csv"
    csv_path.write_text(
        "id,product_name,set_name\naaa,151 Booster Box Case,Pokémon Card 151\n"
    )
    db_path = tmp_path / "pyholofoil.db"

    load_products(str(csv_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT product_name, set_name FROM products").fetchall()
    conn.close()

    assert rows == [("151 Booster Box Case", "Pokémon Card 151")]


def test_main_writes_to_conventional_default_db_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([
        {"id": "aaa", "product_name": "151 Booster Box Case", "set_name": "Pokémon Card 151"},
    ]))

    main([str(json_path)])

    conn = sqlite3.connect(str(tmp_path / "data" / "products.db"))
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()

    assert count == 1


def test_main_picks_up_the_single_file_in_input_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "shiny.json").write_text(json.dumps([
        {"id": "aaa", "product_name": "151 Booster Box Case", "set_name": "Pokémon Card 151"},
    ]))

    main([])

    conn = sqlite3.connect(str(tmp_path / "data" / "products.db"))
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()

    assert count == 1


def test_main_errors_when_input_dir_has_no_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input").mkdir()

    with pytest.raises(SystemExit):
        main([])


def test_main_errors_when_input_dir_has_multiple_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.json").write_text("[]")
    (input_dir / "b.csv").write_text("")

    with pytest.raises(SystemExit) as excinfo:
        main([])

    assert "a.json" in str(excinfo.value)
    assert "b.csv" in str(excinfo.value)


def test_products_overrides_table_creation_is_idempotent(tmp_path):
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    load_products(str(json_path), str(db_path))
    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='products_overrides'"
    ).fetchall()
    conn.close()

    assert tables == [("products_overrides",)]


def test_manual_override_survives_transform_rerun(tmp_path):
    """Per ADR-09 (Policy C): a correction in products_overrides must
    survive a subsequent transform re-run that legitimately updates other
    columns on the same row -- this is the entire reason Policy C was
    chosen over the rejected ephemeral (Policy A) alternative."""
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([
        {"id": "aaa", "product_name": "Wrong Name", "value_total": "10"},
    ]))
    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO products_overrides (id, product_name) VALUES (?, ?)",
        ("aaa", "Correct Name"),
    )
    conn.commit()
    conn.close()

    json_path.write_text(json.dumps([
        {"id": "aaa", "product_name": "Wrong Name", "value_total": "20"},
    ]))
    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT product_name, value_total FROM products_merged WHERE id = ?",
        ("aaa",),
    ).fetchone()
    conn.close()

    assert row == ("Correct Name", "20")


def test_products_merged_falls_back_to_products_when_no_override(tmp_path):
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([
        {"id": "aaa", "product_name": "151 Booster Box Case"},
    ]))

    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT product_name FROM products_merged WHERE id = ?", ("aaa",)
    ).fetchone()
    conn.close()

    assert row == ("151 Booster Box Case",)


def test_config_declared_override_column_appears_in_merged_view(tmp_path, monkeypatch):
    """Per ADR-10 (Option 4): a column declared in datasette.yaml's
    x-overrides-extra-columns is added to products_overrides and shows up
    in products_merged, even though products itself has no such column."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "datasette.yaml").write_text(
        "databases:\n  products:\n    tables:\n      products_overrides:\n"
        "        x-overrides-extra-columns:\n        - operator_notes\n"
    )
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO products_overrides (id, operator_notes) VALUES (?, ?)",
        ("aaa", "flagged for review"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT operator_notes FROM products_merged WHERE id = ?", ("aaa",)
    ).fetchone()
    conn.close()

    assert row == ("flagged for review",)


def test_config_declared_columns_accumulate_across_runs(tmp_path, monkeypatch):
    """Per ADR-10: products_merged is rebuilt every run, so config-declared
    columns added incrementally across separate transform runs all end up
    reflected, not just the first one."""
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    (tmp_path / "datasette.yaml").write_text(
        "databases:\n  products:\n    tables:\n      products_overrides:\n"
        "        x-overrides-extra-columns:\n        - field_one\n"
    )
    load_products(str(json_path), str(db_path))

    (tmp_path / "datasette.yaml").write_text(
        "databases:\n  products:\n    tables:\n      products_overrides:\n"
        "        x-overrides-extra-columns:\n        - field_one\n        - field_two\n"
    )
    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(products_merged)")}
    conn.close()

    assert {"field_one", "field_two"}.issubset(cols)


def test_config_declared_extra_column_defaults_existing_rows_to_empty_string(
    tmp_path, monkeypatch
):
    """A column declared in x-overrides-extra-columns after a row already
    exists in products_overrides must default that existing row's new
    column to '' (empty string), not SQLite's own NULL default --
    datasette-write-ui's edit-row form errors ("Unsupported type NoneType")
    on any NULL-valued field, so a NULL here would silently break editing
    every pre-existing row the moment the column is declared."""
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    (tmp_path / "datasette.yaml").write_text("")
    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO products_overrides (id) VALUES (?)", ("bbb",)
    )
    conn.commit()
    conn.close()

    (tmp_path / "datasette.yaml").write_text(
        "databases:\n  products:\n    tables:\n      products_overrides:\n"
        "        x-overrides-extra-columns:\n        - sold_remarks\n"
    )
    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT sold_remarks FROM products_overrides WHERE id = ?", ("bbb",)
    ).fetchone()
    conn.close()

    assert row == ("",)


def test_ensure_overrides_extra_column_creation_is_idempotent(tmp_path, monkeypatch):
    """SQLite's ALTER TABLE ADD COLUMN has no IF NOT EXISTS -- a second
    transform run declaring the same config column must not error."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "datasette.yaml").write_text(
        "databases:\n  products:\n    tables:\n      products_overrides:\n"
        "        x-overrides-extra-columns:\n        - operator_notes\n"
    )
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    load_products(str(json_path), str(db_path))
    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    cols = [row[1] for row in conn.execute("PRAGMA table_info(products_overrides)")]
    conn.close()

    assert cols.count("operator_notes") == 1


def test_extra_column_declared_for_one_table_does_not_leak_to_another(
    tmp_path, monkeypatch
):
    """Per ADR-22: a column declared under one overrides table's own
    x-overrides-extra-columns block must not appear on a different
    overrides table -- the pre-ADR-22 flat top-level list applied every
    declared column to every table, and this already corrupted the live
    products_overrides table with sold-only columns."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "datasette.yaml").write_text(
        "databases:\n  products:\n    tables:\n      products_overrides_sold:\n"
        "        x-overrides-extra-columns:\n        - sold_remarks\n"
        "x-overrides-tables:\n  - sold\n"
    )
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    primary_cols = {row[1] for row in conn.execute("PRAGMA table_info(products_overrides)")}
    sold_cols = {row[1] for row in conn.execute("PRAGMA table_info(products_overrides_sold)")}
    conn.close()

    assert "sold_remarks" not in primary_cols
    assert "sold_remarks" in sold_cols


def test_extra_overrides_table_gets_independent_table_and_view(tmp_path, monkeypatch):
    """Per ADR-20: a table declared in x-overrides-tables gets its own
    products_overrides_<name> table and products_merged_<name> view,
    independent of the primary (unsuffixed) pair."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "datasette.yaml").write_text("x-overrides-tables:\n  - reviewer_b\n")
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO products_overrides_reviewer_b (id, product_name) VALUES (?, ?)",
        ("aaa", "Corrected by reviewer B"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT product_name FROM products_merged_reviewer_b WHERE id = ?", ("aaa",)
    ).fetchone()
    primary_row = conn.execute(
        "SELECT product_name FROM products_merged WHERE id = ?", ("aaa",)
    ).fetchone()
    conn.close()

    assert row == ("Corrected by reviewer B",)
    assert primary_row == ("X",)  # primary table untouched by the extra one


def test_extra_overrides_table_creation_is_idempotent(tmp_path, monkeypatch):
    """A second transform run declaring the same extra overrides table
    must not error, duplicate the table, or otherwise corrupt it -- same
    guarantee the primary table already has, extended to a declared
    extra one."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "datasette.yaml").write_text("x-overrides-tables:\n  - reviewer_b\n")
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    load_products(str(json_path), str(db_path))
    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
            "AND name IN ('products_overrides_reviewer_b', 'products_merged_reviewer_b')"
        )
    ]
    conn.close()

    assert sorted(names) == ["products_merged_reviewer_b", "products_overrides_reviewer_b"]


def test_primary_overrides_table_names_unchanged_when_extra_tables_declared(
    tmp_path, monkeypatch
):
    """Per ADR-20: declaring extra overrides tables must never rename or
    otherwise affect the primary products_overrides/products_merged pair
    -- build.py/sync_sheets.py/Makefile default to the literal
    'products_merged' name and must keep working unmodified."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "datasette.yaml").write_text("x-overrides-tables:\n  - reviewer_b\n")
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    conn.close()

    assert {"products_overrides", "products_merged"}.issubset(tables)


def test_generate_overrides_queries_preserves_hand_authored_content(
    tmp_path, monkeypatch
):
    """Per ADR-20: the generator mutates the parsed config structurally via
    ruamel.yaml's round-trip mode, never a plain yaml.safe_load()+dump()
    (confirmed live: that round-trip strips every comment and reorders
    keys in the real datasette.yaml). A hand-written comment and the
    existing copy-to-overrides query must both survive generation
    untouched, and the new entry must appear alongside them."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "datasette.yaml").write_text(
        "databases:\n"
        "  products:\n"
        "    queries:\n"
        "      copy-to-overrides:  # hand-authored, never touched\n"
        "        sql: |-\n"
        "          INSERT INTO products_overrides (id) SELECT id FROM products WHERE id = :id\n"
        "        write: true\n"
        "x-overrides-tables:\n"
        "  - reviewer_b\n"
    )
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    load_products(str(json_path), str(db_path))

    out = (tmp_path / "datasette.yaml").read_text()

    assert "# hand-authored, never touched" in out
    assert "copy-to-overrides:" in out
    assert "copy-to-overrides-reviewer_b:" in out
    assert "products_overrides_reviewer_b" in out
    assert "on_success_redirect: /products/products_overrides_reviewer_b" in out


def test_generate_overrides_queries_is_idempotent(tmp_path, monkeypatch):
    """Running load_products twice with the same declared tables must not
    duplicate the generated canned-query entry."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "datasette.yaml").write_text(
        "databases:\n  products:\n    queries: {}\n"
        "x-overrides-tables:\n  - reviewer_b\n"
    )
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    load_products(str(json_path), str(db_path))
    first = (tmp_path / "datasette.yaml").read_text()
    load_products(str(json_path), str(db_path))
    second = (tmp_path / "datasette.yaml").read_text()

    assert first == second
    assert second.count("copy-to-overrides-reviewer_b:") == 1


def test_generate_overrides_queries_removes_undeclared_entries(tmp_path, monkeypatch):
    """If a previously-declared table is removed from x-overrides-tables,
    its generated canned query must be removed too, not left behind
    pointing at a table that may no longer exist."""
    monkeypatch.chdir(tmp_path)
    yaml_path = tmp_path / "datasette.yaml"
    yaml_path.write_text(
        "databases:\n  products:\n    queries: {}\n"
        "x-overrides-tables:\n  - reviewer_b\n"
    )
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    load_products(str(json_path), str(db_path))
    assert "copy-to-overrides-reviewer_b:" in yaml_path.read_text()

    yaml_path.write_text("databases:\n  products:\n    queries: {}\n")
    load_products(str(json_path), str(db_path))

    assert "copy-to-overrides-reviewer_b:" not in yaml_path.read_text()


def test_generate_overrides_queries_noop_without_queries_section(tmp_path, monkeypatch):
    """A datasette.yaml with no databases.products.queries section (e.g. a
    fresh checkout predating ADR-20) must not error and must not invent
    the section."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "datasette.yaml").write_text("x-overrides-tables:\n  - reviewer_b\n")
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([{"id": "aaa", "product_name": "X"}]))

    load_products(str(json_path), str(db_path))  # must not raise

    assert "copy-to-overrides-reviewer_b" not in (tmp_path / "datasette.yaml").read_text()


def test_load_products_refuses_record_missing_id(tmp_path, monkeypatch):
    """Per ADR-15: a record missing a field records[0] had (e.g. a
    ShinyExport export-format drift dropping "id") must fail loudly, not
    silently write None into the id-keyed primary key -- verified live this
    session that the old .get()-based path did exactly that."""
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "products.db"
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([
        {"id": "aaa", "product_name": "Box"},
        {"product_name": "Missing id"},
    ]))

    with pytest.raises(SystemExit):
        load_products(str(json_path), str(db_path))
