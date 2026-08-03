import json
import re
import sqlite3
from pathlib import Path

from datasette_saved_queries import create_tables
from ruamel.yaml import YAML

from app.transform import load_products


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


def test_copy_to_overrides_column_list_matches_products_overrides_schema(tmp_path):
    """Per REQ-017 (from ADR-18's GATE A Reject): datasette.yaml's
    copy-to-overrides canned query hardcodes a column list. If the input
    schema gains or loses a field, products_overrides' real columns drift
    out of sync with that hardcoded list -- silently, since the query's
    INSERT/SELECT still succeeds, it just omits or errors on the wrong
    columns. This test fails loudly the moment that drift happens, by
    comparing the query's parsed column list against a real
    products_overrides table built the same way `make transform` builds
    one."""
    db_path = tmp_path / "products.db"
    record = {
        "id": "aaa",
        "product_name": "151 Booster Box Case",
        "set_name": "Pokémon Card 151",
        "brand_name": "Pokemon",
        "discriminator": "",
        "rarity": "Sealed",
        "quantity": "2",
        "value_total": "9987.82",
        "value_per_unit": "4993.91",
        "value_currency": "SGD",
        "paid_total": "6350.00",
        "paid_per_unit": "3175.00",
        "paid_currency": "SGD",
        "grade_type": "Ungraded",
        "grade_subtype": "Near Mint",
        "group_name": "Primary",
        "group_wishlist": "",
        "tcgplayer_id": "123",
        "pricecharting_id": "",
        "doubleholo_id": "",
        "date_added": "2026-07-23",
        "tag": "",
    }
    input_path = tmp_path / "shiny.json"
    input_path.write_text(json.dumps([record]))
    load_products(str(input_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    actual_columns = {row[1] for row in conn.execute("PRAGMA table_info(products_overrides)")}
    conn.close()

    repo_datasette_yaml = Path(__file__).parent.parent / "datasette.yaml"
    with open(repo_datasette_yaml) as f:
        config = YAML().load(f)
    sql = config["databases"]["products"]["queries"]["copy-to-overrides"]["sql"]

    def _columns(pattern):
        return set(
            re.search(pattern, sql).group(1).replace("\n", "").replace(" ", "").split(",")
        )

    insert_columns = _columns(r"INSERT INTO products_overrides \(([^)]+)\)")
    select_columns = _columns(r"SELECT\n([\s\S]+?)\nFROM products")

    assert insert_columns == actual_columns
    assert select_columns == actual_columns


def test_copy_to_overrides_sold_column_list_matches_products_overrides_sold_schema(
    tmp_path,
):
    """Same drift check as test_copy_to_overrides_column_list_matches_
    products_overrides_schema, extended to the sold table's own generated
    canned query (ADR-20) -- this coverage gap is what let a narrow test
    fixture's regeneration silently truncate copy-to-overrides-sold's
    column list without any test noticing."""
    db_path = tmp_path / "products.db"
    record = {
        "id": "aaa",
        "product_name": "151 Booster Box Case",
        "set_name": "Pokémon Card 151",
        "brand_name": "Pokemon",
        "discriminator": "",
        "rarity": "Sealed",
        "quantity": "2",
        "value_total": "9987.82",
        "value_per_unit": "4993.91",
        "value_currency": "SGD",
        "paid_total": "6350.00",
        "paid_per_unit": "3175.00",
        "paid_currency": "SGD",
        "grade_type": "Ungraded",
        "grade_subtype": "Near Mint",
        "group_name": "Primary",
        "group_wishlist": "",
        "tcgplayer_id": "123",
        "pricecharting_id": "",
        "doubleholo_id": "",
        "date_added": "2026-07-23",
        "tag": "",
    }
    input_path = tmp_path / "shiny.json"
    input_path.write_text(json.dumps([record]))
    (tmp_path / "datasette.local.yaml").write_text("x-overrides-tables:\n- sold\n")
    load_products(str(input_path), str(db_path))

    conn = sqlite3.connect(str(db_path))
    actual_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(products_overrides_sold)")
    }
    conn.close()

    repo_datasette_yaml = Path(__file__).parent.parent / "datasette.yaml"
    with open(repo_datasette_yaml) as f:
        config = YAML().load(f)
    sql = config["databases"]["products"]["queries"]["copy-to-overrides-sold"]["sql"]

    def _columns(pattern):
        return set(
            re.search(pattern, sql).group(1).replace("\n", "").replace(" ", "").split(",")
        )

    insert_columns = _columns(r"INSERT INTO products_overrides_sold \(([^)]+)\)")
    select_columns = _columns(r"SELECT ([^F]+) FROM products")

    assert insert_columns == actual_columns
    assert select_columns == actual_columns
