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
