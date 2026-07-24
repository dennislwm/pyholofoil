import argparse
import csv
import json
import os
import sqlite3
from datetime import datetime, timezone


def _read_records(input_path):
    """Per REQ-008: dispatch on file extension into the same list[dict]
    shape, whichever format the caller drops -- data is the first-class
    contract, file format is incidental."""
    if input_path.endswith(".csv"):
        with open(input_path, newline="") as f:
            return list(csv.DictReader(f))
    with open(input_path) as f:
        return json.load(f)


def load_products(input_path, db_path):
    """Load a flat ShinyExport-shaped JSON or CSV array into one flat SQLite
    table.

    Per ADR-01: single flat table, scoped to catalog-resolved sources
    (records carrying a catalog-match ID such as tcgplayer_id).

    Per ADR-06: id-keyed upsert. `id` is the only field observed stable
    across real snapshots -- re-running on the same or a new file updates
    existing rows in place rather than duplicating or partitioning by a
    caller-supplied date. `last_updated` is set by the write itself, never
    caller-supplied, so it cannot be mismatched the way snapshot_date was.
    """
    records = _read_records(input_path)
    if not records:
        return

    columns = list(records[0].keys()) + ["last_updated"]
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS products "
        f"({', '.join(f'{c} TEXT' for c in columns)}, "
        "PRIMARY KEY (id))"
    )
    placeholders = ", ".join("?" for _ in columns)
    update_cols = [c for c in columns if c != "id"]
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        f"INSERT INTO products ({', '.join(columns)}) VALUES ({placeholders}) "
        "ON CONFLICT(id) DO UPDATE SET "
        + ", ".join(f"{c} = excluded.{c}" for c in update_cols),
        [tuple(r.get(c) for c in columns[:-1]) + (now,) for r in records],
    )
    conn.commit()
    conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
    parser.add_argument("--db-path", default="data/products.db")
    args = parser.parse_args(argv)
    os.makedirs(os.path.dirname(args.db_path), exist_ok=True)
    load_products(args.input_path, args.db_path)


if __name__ == "__main__":
    main()
