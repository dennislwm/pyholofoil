import argparse
import csv
import json
import os
import sqlite3
from datetime import datetime, timezone

import jsonschema
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

_yaml = YAML()


def _validate_records(records, schema_path="input_schema.json"):
    """Per ADR-15: fail loudly on a ShinyExport format drift (a renamed,
    dropped, or missing field) instead of silently writing NULL into an
    id-keyed row. Raises on the first invalid record, naming its index."""
    with open(schema_path) as f:
        schema = json.load(f)
    for i, record in enumerate(records):
        try:
            jsonschema.validate(instance=record, schema=schema)
        except jsonschema.ValidationError as e:
            raise SystemExit(f"Record {i} failed validation: {e.message}") from e


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


def _load_extra_override_columns(config_path="datasette.yaml", name=None):
    """Per ADR-10 (Option 4) and ADR-22 (Option 1): override-only columns
    (present in an overrides table but not products) are declared durably
    in datasette.yaml, not inferred from a live database inspection --
    surviving a fresh checkout or a schema-recovery rebuild (ADR-08)
    without relying on the operator's memory.

    Per ADR-22: scoped per table under Datasette's own
    databases.<db>.tables.<table_name> config block -- the same shape
    already used for products_overrides.permissions -- so a column
    declared for one overrides table is never silently applied to
    another. name=None mirrors _ensure_overrides()'s own convention: the
    primary (unsuffixed) products_overrides table."""
    if not os.path.exists(config_path):
        return []
    with open(config_path) as f:
        config = _yaml.load(f) or {}
    table = "products_overrides" if name is None else f"products_overrides_{name}"
    tables = config.get("databases", {}).get("products", {}).get("tables", {})
    return (tables.get(table) or {}).get("x-overrides-extra-columns") or []


def _load_extra_overrides_tables(config_path="datasette.yaml"):
    """Per ADR-20 (Option 2): names of ADDITIONAL overrides tables beyond
    the implicit primary one. Primary stays products_overrides/
    products_merged, completely unchanged -- no rename, no migration, no
    default name to invent. Empty list means zero behavior change from
    before this ADR."""
    if not os.path.exists(config_path):
        return []
    with open(config_path) as f:
        config = _yaml.load(f) or {}
    return config.get("x-overrides-tables") or []


def _ensure_overrides(conn, columns, name=None):
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
    config-declared list instead of a diff against `columns`.

    Per ADR-20: `name=None` is the primary table (today's exact
    unsuffixed products_overrides/products_merged); any other value
    produces products_overrides_<name>/products_merged_<name>, so
    build.py/sync_sheets.py/Makefile's products_merged default never
    needs to change."""
    table = "products_overrides" if name is None else f"products_overrides_{name}"
    view = "products_merged" if name is None else f"products_merged_{name}"

    override_cols = [c for c in columns if c != "last_updated"]
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {table} "
        f"({', '.join(f'{c} TEXT' for c in override_cols)}, "
        "PRIMARY KEY (id))"
    )

    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    extra_cols = [
        c for c in _load_extra_override_columns(name=name) if c not in override_cols
    ]
    for c in extra_cols:
        if c not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {c} TEXT DEFAULT ''")

    all_override_cols = override_cols + extra_cols
    merge_cols = ", ".join(
        "COALESCE(p.id, o.id) AS id" if c == "id"
        else f"COALESCE(o.{c}, p.{c}) AS {c}" if c in override_cols
        else f"o.{c}"
        for c in all_override_cols
    )
    conn.execute(f"DROP VIEW IF EXISTS {view}")
    conn.execute(
        f"CREATE VIEW {view} AS "
        f"SELECT {merge_cols}, p.last_updated FROM products p "
        f"FULL OUTER JOIN {table} o ON p.id = o.id"
    )


def _generate_overrides_queries(columns, config_path="datasette.yaml"):
    """Per ADR-20 (Option 2): writes canned write-queries per declared extra
    overrides table into datasette.yaml, via ruamel.yaml's round-trip mode
    -- structural mutation of the parsed config, not a plain-text marker
    splice. ruamel preserves every comment, key order, and the
    hand-authored `copy-to-overrides` query's block-scalar formatting
    untouched (confirmed live against this file); plain PyYAML's
    safe_load()+dump() strips all of that (also confirmed live).

    Two query kinds, both keyed off the same per-table config: a
    `copy-to-overrides-<name>` (always) and, only when that table declares
    `x-overrides-extra-columns`, a `backfill-null-extra-columns-<name>`
    (COALESCE-backfills existing rows' NULLs left by an ad hoc
    `datasette-edit-schema` column add -- config-declared columns already
    get their DEFAULT '' at ALTER TABLE time via `_ensure_overrides`, per
    REQ-024; this covers the UI-added path that doesn't). Generated
    entries are identified by their `copy-to-overrides-`/
    `backfill-null-extra-columns-` prefixes (a bare `copy-to-overrides` key
    never matches either) -- any such key not matching the current
    declared-names list, or (for backfill) no longer having extra columns,
    is removed each run, so renaming/removing a declared table or its
    extra columns cleans up after itself, not just adding new ones."""
    names = _load_extra_overrides_tables(config_path)
    override_cols = [c for c in columns if c != "last_updated"]
    col_csv = ", ".join(override_cols)

    if not os.path.exists(config_path):
        return
    with open(config_path) as f:
        raw_config_text = f.read()
    config = _yaml.load(raw_config_text) or {}

    products_map = config.get("databases", {}).get("products", {})
    queries = products_map.get("queries")
    if queries is None:
        return  # no queries section to generate into -- nothing to do

    tables = products_map.get("tables")
    if tables is not None:
        for name in names:
            table = f"products_overrides_{name}"
            if table not in tables:
                tables[table] = {}
            tables[table].setdefault("permissions", {
                "insert-row": {"id": "operator"},
                "update-row": {"id": "operator"},
                "delete-row": {"id": "operator"},
            })

    for key in [k for k in queries if k.startswith("copy-to-overrides-")]:
        if key[len("copy-to-overrides-"):] not in names:
            del queries[key]
    for key in [k for k in queries if k.startswith("backfill-null-extra-columns-")]:
        if key[len("backfill-null-extra-columns-"):] not in names:
            del queries[key]

    for name in names:
        queries[f"copy-to-overrides-{name}"] = {
            "sql": LiteralScalarString(
                f"INSERT INTO products_overrides_{name} ({col_csv})\n"
                f"SELECT {col_csv} FROM products WHERE id = :id\n"
                "ON CONFLICT(id) DO NOTHING"
            ),
            "write": True,
            "on_success_redirect": f"/products/products_overrides_{name}",
        }
        extra_cols = _load_extra_override_columns(config_path, name=name)
        if extra_cols:
            queries[f"backfill-null-extra-columns-{name}"] = {
                "sql": LiteralScalarString(
                    f"UPDATE products_overrides_{name} SET\n"
                    + ",\n".join(f"  {c} = COALESCE({c}, '')" for c in extra_cols)
                ),
                "write": True,
                "on_success_redirect": f"/products/products_overrides_{name}",
            }
        else:
            queries.pop(f"backfill-null-extra-columns-{name}", None)

    # REQ-034: mark the generated block so a reader inspecting datasette.yaml
    # directly doesn't mistake it for hand-authored/hand-duplicated config.
    # Guarded: yaml_set_comment_before_after_key appends rather than replaces
    # on repeat calls, so re-setting it unconditionally would duplicate the
    # comment on every `make transform` run.
    if "Generated by make transform (ADR-20)" not in raw_config_text:
        products_map.yaml_set_comment_before_after_key(
            "queries",
            before='Generated by make transform (ADR-20) -- do not '
            'hand-edit, see README "declaring an extra overrides table"',
        )

    with open(config_path, "w") as f:
        _yaml.dump(config, f)


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
    _validate_records(records)

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
    # Per REQ-035: every ShinyExport is a full-inventory snapshot, so an id
    # absent from this run's file has been genuinely removed, not partially
    # exported -- hard-delete it rather than leaving it stale forever.
    ids = [r.get("id") for r in records]
    conn.execute(
        f"DELETE FROM products WHERE id NOT IN ({', '.join('?' for _ in ids)})",
        ids,
    )
    _ensure_overrides(conn, columns)
    for name in _load_extra_overrides_tables():
        _ensure_overrides(conn, columns, name)
    _generate_overrides_queries(columns)
    conn.commit()
    conn.close()


def _pick_input_file(input_dir):
    """Per REQ-009: pick up whichever single file is present in input_dir,
    no fixed filename required. Never guess a "latest" file -- mtime is
    fragile (depends on how a file was copied) and the filename is not
    parsed for a date."""
    files = sorted(
        f
        for f in (os.listdir(input_dir) if os.path.isdir(input_dir) else [])
        if f.endswith((".csv", ".json"))
        and os.path.isfile(os.path.join(input_dir, f))
    )
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
