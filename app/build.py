import argparse
import json
import os
import sqlite3


def build_redacted(full_db_path, redacted_db_path, sensitive_fields_path):
    """Materialize a redacted copy of the products table, per ADR-04.

    Column subset (all columns except those listed in sensitive_fields_path)
    is written into a fresh table in redacted_db_path via CREATE TABLE AS
    SELECT -- full_db_path is never mutated.

    Idempotent: re-running replaces the redacted table rather than
    duplicating rows.
    """
    with open(sensitive_fields_path) as f:
        sensitive_fields = set(json.load(f))

    conn = sqlite3.connect(full_db_path)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(products)")]
    kept = [c for c in columns if c not in sensitive_fields]

    conn.execute("ATTACH DATABASE ? AS redacted", (redacted_db_path,))
    conn.execute("DROP TABLE IF EXISTS redacted.products")
    conn.execute(
        f"CREATE TABLE redacted.products AS SELECT {', '.join(kept)} FROM products"
    )
    conn.commit()
    conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-db-path", default="data/products.db")
    parser.add_argument("--redacted-db-path", default="data/products_public.db")
    parser.add_argument("--sensitive-fields-path", default="sensitive_fields.json")
    args = parser.parse_args(argv)
    os.makedirs(os.path.dirname(args.redacted_db_path) or ".", exist_ok=True)
    build_redacted(args.full_db_path, args.redacted_db_path, args.sensitive_fields_path)


if __name__ == "__main__":
    main()
