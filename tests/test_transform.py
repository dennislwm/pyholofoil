import json
import sqlite3

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
