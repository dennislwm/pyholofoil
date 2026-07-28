from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))
from canned_queries import canned_queries  # noqa: E402


def test_canned_queries_reads_products_database_queries():
    Path("datasette.yaml").write_text(
        "databases:\n  products:\n    queries:\n"
        "      copy-to-overrides:\n        sql: SELECT 1\n"
    )
    assert canned_queries(database="products") == {
        "copy-to-overrides": {"sql": "SELECT 1"}
    }


def test_canned_queries_ignores_other_databases():
    Path("datasette.yaml").write_text(
        "databases:\n  products:\n    queries:\n"
        "      copy-to-overrides:\n        sql: SELECT 1\n"
    )
    assert canned_queries(database="other") == {}


def test_canned_queries_picks_up_a_change_without_restart():
    """Per ADR-25: this is the whole point of the plugin -- the same
    process must see a rewritten file on its next call, not a cached
    startup snapshot."""
    Path("datasette.yaml").write_text(
        "databases:\n  products:\n    queries:\n"
        "      copy-to-overrides:\n        sql: SELECT 1\n"
    )
    before = canned_queries(database="products")

    Path("datasette.yaml").write_text(
        "databases:\n  products:\n    queries:\n"
        "      copy-to-overrides:\n        sql: SELECT 2\n"
        "      copy-to-overrides-sold:\n        sql: SELECT 3\n"
    )
    after = canned_queries(database="products")

    assert before != after
    assert after == {
        "copy-to-overrides": {"sql": "SELECT 2"},
        "copy-to-overrides-sold": {"sql": "SELECT 3"},
    }


def test_canned_queries_missing_config_file_returns_empty():
    assert canned_queries(database="products") == {}
