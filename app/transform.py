import argparse
import csv
import json
import os
import sqlite3
from datetime import datetime, timezone

import yaml


def _read_records(input_path):
    """Per REQ-008: dispatch on file extension into the same list[dict]
    shape, whichever format the caller drops -- data is the first-class
    contract, file format is incidental."""
    if input_path.endswith(".csv"):
        with open(input_path, newline="") as f:
            return list(csv.DictReader(f))
    with open(input_path) as f:
        return json.load(f)


def _check_schema(conn, expected_columns, db_path):
    """Per ADR-08: generically compare products' actual schema (columns and
    primary key) against what THIS run currently expects, rather than
    checking for one hardcoded column -- catches staleness from any
    schema-changing ADR, not just the one already known. No-op if the
    table doesn't exist yet."""
    info = conn.execute("PRAGMA table_info(products)").fetchall()
    if not info:
        return
    actual_columns = {row[1] for row in info}
    pk_column = next((row[1] for row in info if row[5] == 1), None)
    if not expected_columns.issubset(actual_columns) or pk_column != "id":
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        raise SystemExit(
            "products table is stale (schema mismatch with what this "
            "version of transform expects) -- rename it to recover: "
            f'sqlite3 {db_path} "ALTER TABLE products RENAME TO '
            f'products_stale_{timestamp}"'
        )


def _load_extra_override_columns(config_path="datasette.yaml"):
    """Per ADR-10 (Option 4): override-only columns (present in
    products_overrides but not products) are declared durably in
    datasette.yaml, not inferred from a live database inspection --
    surviving a fresh checkout or a schema-recovery rebuild (ADR-08)
    without relying on the operator's memory."""
    if not os.path.exists(config_path):
        return []
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    return config.get("x-overrides-extra-columns") or []


def _ensure_overrides(conn, columns):
    """Per ADR-09 (Policy C): products_overrides mirrors products' input
    columns (not last_updated, which is transform-internal bookkeeping),
    all nullable except id. transform never writes to this table --
    write-ui's insert/update/delete permissions are scoped to it via
    datasette.yaml, leaving products read-only through the UI.

    Per ADR-10 (Option 4): products_merged is rebuilt every run (not
    CREATE VIEW IF NOT EXISTS, which never adapts once created) to also
    include any config-declared override-only column -- SQLite's ALTER
    TABLE ADD COLUMN has no IF NOT EXISTS, so each declared column still
    needs one existence check before being added, same primitive as
    _check_schema (ADR-08); what changes is WHICH columns get checked, a
    config-declared list instead of a diff against `columns`."""
    override_cols = [c for c in columns if c != "last_updated"]
    conn.execute(
        "CREATE TABLE IF NOT EXISTS products_overrides "
        f"({', '.join(f'{c} TEXT' for c in override_cols)}, "
        "PRIMARY KEY (id))"
    )

    existing = {row[1] for row in conn.execute("PRAGMA table_info(products_overrides)")}
    extra_cols = [
        c for c in _load_extra_override_columns() if c not in override_cols
    ]
    for c in extra_cols:
        if c not in existing:
            conn.execute(f"ALTER TABLE products_overrides ADD COLUMN {c} TEXT")

    all_override_cols = override_cols + extra_cols
    merge_cols = ", ".join(
        "p.id" if c == "id"
        else f"COALESCE(o.{c}, p.{c}) AS {c}" if c in override_cols
        else f"o.{c}"
        for c in all_override_cols
    )
    conn.execute("DROP VIEW IF EXISTS products_merged")
    conn.execute(
        "CREATE VIEW products_merged AS "
        f"SELECT {merge_cols}, p.last_updated FROM products p "
        "LEFT JOIN products_overrides o ON p.id = o.id"
    )


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
    _check_schema(conn, set(columns), db_path)
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
    _ensure_overrides(conn, columns)
    conn.commit()
    conn.close()


def _pick_input_file(input_dir):
    """Per REQ-009: pick up whichever single file is present in input_dir,
    no fixed filename required. Never guess a "latest" file -- mtime is
    fragile (depends on how a file was copied) and the filename is not
    parsed for a date."""
    files = sorted(os.listdir(input_dir)) if os.path.isdir(input_dir) else []
    if not files:
        raise SystemExit(f"No input file found in {input_dir}/")
    if len(files) > 1:
        raise SystemExit(
            f"Multiple input files found in {input_dir}/: {', '.join(files)}"
        )
    return os.path.join(input_dir, files[0])


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path", nargs="?", default=None)
    parser.add_argument("--db-path", default="data/products.db")
    parser.add_argument("--input-dir", default="input")
    args = parser.parse_args(argv)
    input_path = args.input_path or _pick_input_file(args.input_dir)
    os.makedirs(os.path.dirname(args.db_path), exist_ok=True)
    load_products(input_path, args.db_path)


if __name__ == "__main__":
    main()
