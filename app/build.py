import argparse
import os
import shutil
import sqlite3

from ruamel.yaml import YAML

_yaml = YAML()


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
    return set(data.get("_global", [])) | set(data.get(source_table, []))


def _load_all_sensitive_fields(path):
    """Union of every declared table's sensitive fields plus "_global" --
    used by verify_redacted(), which (per Makefile's deploy target) is
    never told which source_table produced a given redacted artifact. A
    superset check is safe: it can only catch more leaks, never miss one --
    a table lacking a column can never trigger on an unrelated table's
    field name.
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
    mutated.

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

    conn.execute("ATTACH DATABASE ? AS redacted", (redacted_db_path,))
    conn.execute("DROP TABLE IF EXISTS redacted.products")
    conn.execute(
        f"CREATE TABLE redacted.products AS SELECT {', '.join(kept)} FROM {source_table}"
    )
    conn.commit()
    conn.close()


def verify_redacted(redacted_db_path, sensitive_fields_path, table="products"):
    """Refuse to let a non-redacted artifact reach deploy, per REQ-013.

    Checks the actual file about to be published contains none of the
    columns sensitive_fields.yaml says must be excluded, for ANY declared
    table (per ADR-27 -- this check doesn't know which source_table built
    the artifact, so it checks the union across every table's list, which
    is safe: see _load_all_sensitive_fields()'s docstring). Catches a
    stale REDACTED_DB_PATH override or any artifact that reached this path
    without going through build_redacted().
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
