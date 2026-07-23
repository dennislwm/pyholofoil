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

    load_products(str(json_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT product_name, set_name, rarity FROM products ORDER BY product_name").fetchall()
    conn.close()

    assert rows == [
        ("151 Booster Box Case", "Pokémon Card 151", "Sealed"),
        ("151 Booster Bundle", "Scarlet & Violet 151", "Sealed"),
    ]
