import json

import pytest


@pytest.fixture(autouse=True)
def _input_schema(tmp_path):
    """Per ADR-15: load_products() reads input_schema.json relative to cwd.
    Tests that monkeypatch.chdir(tmp_path) need a copy there; this is a
    harmless unused file for tests that don't chdir."""
    (tmp_path / "input_schema.json").write_text(json.dumps({"required": ["id"]}))


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """Every test runs from a fresh tmp_path by default, so a function
    relying on a relative default path (e.g. transform.py's
    config_path="datasette.yaml") never reads or overwrites the real
    project's datasette.yaml -- confirmed live: several tests without
    their own monkeypatch.chdir were silently regenerating the real
    file's copy-to-overrides-sold canned query down to whatever narrow
    column set that test's fixture happened to use. A test that needs a
    specific cwd chdirs again itself; re-chdiring to the same
    already-isolated dir is a no-op."""
    monkeypatch.chdir(tmp_path)
