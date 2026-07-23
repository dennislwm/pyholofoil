import json
import sqlite3

from app.transform import load_products


def test_load_products_creates_one_flat_table(tmp_path):
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([
        {
            "product_name": "151 Booster Box Case",
            "set_name": "Pokémon Card 151",
            "brand_name": "Pokemon",
            "rarity": "Sealed",
            "tcgplayer_id": "null",
        },
        {
            "product_name": "151 Booster Bundle",
            "set_name": "Scarlet & Violet 151",
            "brand_name": "Pokemon",
            "rarity": "Sealed",
            "tcgplayer_id": "502000",
        },
    ]))
    db_path = tmp_path / "pyholofoil.db"

    load_products(str(json_path), str(db_path), "20260528")

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT product_name, set_name, rarity, snapshot_date FROM products ORDER BY product_name"
    ).fetchall()
    conn.close()

    assert rows == [
        ("151 Booster Box Case", "Pokémon Card 151", "Sealed", "20260528"),
        ("151 Booster Bundle", "Scarlet & Violet 151", "Sealed", "20260528"),
    ]


def test_load_products_is_idempotent_on_same_snapshot(tmp_path):
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([
        {"product_name": "151 Booster Box Case", "set_name": "Pokémon Card 151"},
    ]))
    db_path = tmp_path / "pyholofoil.db"

    load_products(str(json_path), str(db_path), "20260528")
    load_products(str(json_path), str(db_path), "20260528")

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()

    assert count == 1


def test_load_products_keeps_different_snapshots_separate(tmp_path):
    json_path = tmp_path / "shiny.json"
    json_path.write_text(json.dumps([
        {"product_name": "151 Booster Box Case", "set_name": "Pokémon Card 151"},
    ]))
    db_path = tmp_path / "pyholofoil.db"

    load_products(str(json_path), str(db_path), "20260528")
    load_products(str(json_path), str(db_path), "20260708")

    conn = sqlite3.connect(str(db_path))
    dates = sorted(r[0] for r in conn.execute("SELECT snapshot_date FROM products").fetchall())
    conn.close()

    assert dates == ["20260528", "20260708"]
