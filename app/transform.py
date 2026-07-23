import json
import sqlite3


def load_products(json_path, db_path, table_name="products"):
    """Load a flat ShinyExport-shaped JSON array into one flat SQLite table.

    Per ADR-01: single flat table, scoped to catalog-resolved sources
    (records carrying a catalog-match ID such as tcgplayer_id).
    """
    with open(json_path) as f:
        records = json.load(f)
    if not records:
        return

    columns = list(records[0].keys())
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {table_name} "
        f"({', '.join(f'{c} TEXT' for c in columns)})"
    )
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})",
        [tuple(r.get(c) for c in columns) for r in records],
    )
    conn.commit()
    conn.close()
