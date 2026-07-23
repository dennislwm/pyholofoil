import json
import sqlite3


def load_products(json_path, db_path, snapshot_date, table_name="products"):
    """Load a flat ShinyExport-shaped JSON array into one flat SQLite table.

    Per ADR-01: single flat table, scoped to catalog-resolved sources
    (records carrying a catalog-match ID such as tcgplayer_id).

    Per REQ-004: snapshot_date attributes each row to the snapshot it came
    from -- set at load time by the caller, not parsed from the filename
    inside this function.

    Idempotent: re-running with the same snapshot_date replaces that
    snapshot's rows rather than duplicating them.
    """
    with open(json_path) as f:
        records = json.load(f)
    if not records:
        return

    columns = list(records[0].keys()) + ["snapshot_date"]
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {table_name} "
        f"({', '.join(f'{c} TEXT' for c in columns)})"
    )
    conn.execute(
        f"DELETE FROM {table_name} WHERE snapshot_date = ?", (snapshot_date,)
    )
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})",
        [tuple(r.get(c) for c in columns[:-1]) + (snapshot_date,) for r in records],
    )
    conn.commit()
    conn.close()
