import argparse
import json
import sqlite3
import subprocess


def build_rows(db_path, source_table):
    """Read source_table into a header + data row-list, per ADR-14.

    All values are cast to str -- every column in this pipeline is TEXT
    already (REQ-011), so this never lossy-converts a real value.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.execute(f"SELECT * FROM {source_table}")
    header = [d[0] for d in cur.description]
    rows = [[("" if v is None else str(v)) for v in row] for row in cur.fetchall()]
    conn.close()
    return [header] + rows


def sync_to_sheet(spreadsheet_id, rows, sheet_range="Sheet1"):
    """Push rows into spreadsheet_id, per ADR-14.

    Clear-then-update, not append -- re-running this with the same data
    leaves the sheet in the same state (idempotent), where append would
    duplicate every row on every run.
    """
    subprocess.run(
        [
            "gws",
            "sheets",
            "spreadsheets",
            "values",
            "clear",
            "--params",
            json.dumps({"spreadsheetId": spreadsheet_id, "range": sheet_range}),
        ],
        check=True,
    )
    subprocess.run(
        [
            "gws",
            "sheets",
            "spreadsheets",
            "values",
            "update",
            "--params",
            json.dumps(
                {
                    "spreadsheetId": spreadsheet_id,
                    "range": sheet_range,
                    "valueInputOption": "RAW",
                }
            ),
            "--json",
            json.dumps({"values": rows}),
        ],
        check=True,
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="data/products.db")
    parser.add_argument("--source-table", default="products_merged")
    parser.add_argument("--spreadsheet-id", required=True)
    parser.add_argument("--range", default="Sheet1")
    args = parser.parse_args(argv)
    rows = build_rows(args.db_path, args.source_table)
    sync_to_sheet(args.spreadsheet_id, rows, args.range)


if __name__ == "__main__":
    main()
