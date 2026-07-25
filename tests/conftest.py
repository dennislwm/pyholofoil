import json

import pytest


@pytest.fixture(autouse=True)
def _input_schema(tmp_path):
    """Per ADR-15: load_products() reads input_schema.json relative to cwd.
    Tests that monkeypatch.chdir(tmp_path) need a copy there; this is a
    harmless unused file for tests that don't chdir."""
    (tmp_path / "input_schema.json").write_text(json.dumps({"required": ["id"]}))
