import argparse
import os
import shutil
import sqlite3

from ruamel.yaml import YAML

_yaml = YAML()


def _parse_entry(value):
    """A "_global" or per-table entry is either a bare list (back-compat:
    columns only, sensitive_fields.yaml's original ADR-27 shape) or a dict
    with optional "columns" (list) and "rows" (a WHERE fragment, REQ-032)
    keys. Returns (columns_set, rows_fragment_or_none).
    """
    if isinstance(value, list):
        return set(value), None
    if value is None:
        return set(), None
    return set(value.get("columns", [])), value.get("rows")


def _load_sensitive_fields(path, source_table):
    """Per ADR-27: sensitive_fields.yaml is a mapping with a "_global" key
    (applied to every table) plus optional per-table keys keyed by
    source_table name, adding to it. Back-compat: a plain list (the old
    flat sensitive_fields.json shape) is treated entirely as "_global" --
    zero declared per-table entries means zero behavior change.
    """
    with open(path) as f:
        data = _yaml.load(f) or []
    if isinstance(data, list):
        return set(data)
    global_columns, _ = _parse_entry(data.get("_global", []))
    table_columns, _ = _parse_entry(data.get(source_table, []))
    return global_columns | table_columns


def _load_row_filter(path, source_table):
    """Per REQ-032: an optional "rows" WHERE fragment declared under
    "_global" and/or a per-table key, same config file as the column
    redaction list. Both fragments apply when both are declared (combined
    via AND). None means no row filtering -- every row passes through,
    matching pre-REQ-032 behavior. Back-compat: a plain list (old flat
    shape) has no "rows" key, so it always returns None.
    """
    with open(path) as f:
        data = _yaml.load(f) or []
    if isinstance(data, list):
        return None
    _, global_rows = _parse_entry(data.get("_global", []))
    _, table_rows = _parse_entry(data.get(source_table, []))
    fragments = [f for f in (global_rows, table_rows) if f]
    if not fragments:
        return None
    return " AND ".join(f"({f})" for f in fragments)


def _load_all_sensitive_fields(path):
    """Union of every declared table's sensitive fields plus "_global" --
    used by verify_redacted(), which (per Makefile's deploy target) is
    never told which source_table produced a given redacted artifact.

    No false negatives: a real leak declared under any table's key is
    always caught, regardless of which table actually built the artifact.

    False positive is possible, though not triggered by any config
    declared today: if a column name is listed under one table's key but
    also legitimately exists, unredacted, as a genuinely shared/different
    column on another table, the union check flags it even when the
    artifact being verified is correctly redacted. Acceptable for now
    (fail-safe direction, not fail-open) but not accident-proof -- avoid
    reusing a column name across tables' per-table keys unless it really
    should be redacted everywhere.
    """
    with open(path) as f:
        data = _yaml.load(f) or []
    if isinstance(data, list):
        return set(data)
    fields = set()
    for values in data.values():
        fields |= set(values)
    return fields


def build_redacted(
    full_db_path, redacted_db_path, sensitive_fields_path, approved_file_path, source_table
):
    """Materialize a redacted copy of products into redacted_db_path, per ADR-04.

    Column subset (all columns except those listed in sensitive_fields_path
    for source_table, per ADR-27) is read from source_table (default
    products_merged, per REQ-012 -- includes any operator corrections from
    products_overrides, ADR-09) and written into a fresh table in
    redacted_db_path via CREATE TABLE AS SELECT -- full_db_path is never
    mutated. Row subset (per REQ-032): an optional "rows" WHERE fragment in
    sensitive_fields_path (same _global/per-table shape as the column list)
    filters which rows are kept -- absent config means no filtering, every
    row passes through.

    Idempotent: re-running replaces the redacted table rather than
    duplicating rows.

    Per ADR-05: refuses to run unless approved_file_path's contents match
    MAX(last_updated) in products -- the sidecar records which reviewed
    snapshot a person approved (ADR-06's last_updated anchor), the same way
    sensitive_fields.yaml already records the redaction contract. The
    approval check always reads products directly (last_updated is not
    projected through products_merged), independent of source_table.
    """
    sensitive_fields = _load_sensitive_fields(sensitive_fields_path, source_table)
    row_filter = _load_row_filter(sensitive_fields_path, source_table)

    conn = sqlite3.connect(full_db_path)
    current_anchor = conn.execute("SELECT MAX(last_updated) FROM products").fetchone()[0]
    if not os.path.exists(approved_file_path):
        raise SystemExit(
            f"No approval on record ({approved_file_path} missing) -- "
            f"refusing to build from an unreviewed dataset."
        )
    approved_anchor = open(approved_file_path).read().strip()
    if approved_anchor != current_anchor:
        raise SystemExit(
            f"products.db has changed since approval -- refusing to build. "
            f"Approved: {approved_anchor!r}, current: {current_anchor!r}."
        )

    # ponytail: source_table/columns are f-string interpolated into SQL, not
    # parameterized (SQLite params can't bind identifiers). Safe today since
    # source_table only ever comes from a trusted local CLI/Makefile arg --
    # validate against this PRAGMA's own column list first if that ever
    # changes to less-trusted input.
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({source_table})")]
    kept = [c for c in columns if c not in sensitive_fields]

    where_clause = f" WHERE {row_filter}" if row_filter else ""
    conn.execute("ATTACH DATABASE ? AS redacted", (redacted_db_path,))
    conn.execute("DROP TABLE IF EXISTS redacted.products")
    conn.execute(
        f"CREATE TABLE redacted.products AS SELECT {', '.join(kept)} "
        f"FROM {source_table}{where_clause}"
    )
    conn.commit()
    conn.close()


def verify_redacted(redacted_db_path, sensitive_fields_path, table="products"):
    """Refuse to let a non-redacted artifact reach deploy, per REQ-013.

    Checks the actual file about to be published contains none of the
    columns sensitive_fields.yaml says must be excluded, for ANY declared
    table (per ADR-27 -- this check doesn't know which source_table built
    the artifact, so it checks the union across every table's list --
    no false negatives, but see _load_all_sensitive_fields()'s docstring
    for a false-positive edge case). Catches a stale REDACTED_DB_PATH
    override or any artifact that reached this path without going through
    build_redacted().
    """
    sensitive_fields = _load_all_sensitive_fields(sensitive_fields_path)
    conn = sqlite3.connect(redacted_db_path)
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    conn.close()
    leaked = columns & sensitive_fields
    if leaked:
        raise SystemExit(
            f"{redacted_db_path} contains sensitive field(s) {sorted(leaked)} -- "
            f"refusing to deploy. Re-run build, or check REDACTED_DB_PATH."
        )


def publish_static(redacted_db_path, docs_dir="docs"):
    """Copy the redacted artifact into a static host's serving directory
    (e.g. GitHub Pages' docs/), per ADR-16 -- datasette-lite loads this file
    directly in the visitor's browser, no server involved. Idempotent:
    overwrites the same destination filename rather than accumulating copies.
    """
    os.makedirs(docs_dir, exist_ok=True)
    dest_path = os.path.join(docs_dir, "products_public.db")
    shutil.copyfile(redacted_db_path, dest_path)
    return dest_path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-db-path", default="data/products.db")
    parser.add_argument("--redacted-db-path", default="data/products_public.db")
    parser.add_argument("--sensitive-fields-path", default="sensitive_fields.yaml")
    parser.add_argument("--approved-file-path", default="data/products.approved")
    parser.add_argument("--source-table", default="products_merged")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--publish-static", action="store_true")
    parser.add_argument("--docs-dir", default="docs")
    args = parser.parse_args(argv)
    if args.verify_only:
        verify_redacted(args.redacted_db_path, args.sensitive_fields_path)
        return
    if args.publish_static:
        dest = publish_static(args.redacted_db_path, args.docs_dir)
        print(dest)
        return
    os.makedirs(os.path.dirname(args.redacted_db_path) or ".", exist_ok=True)
    build_redacted(
        args.full_db_path,
        args.redacted_db_path,
        args.sensitive_fields_path,
        args.approved_file_path,
        args.source_table,
    )


if __name__ == "__main__":
    main()
