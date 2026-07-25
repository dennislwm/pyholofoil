.PHONY: help setup status test explore transform build
SHELL := /bin/bash

help:
	@echo ""
	@echo "=== Targets ==="
	@echo "  help       Show this help"
	@echo "  setup      pipenv install from Pipfile"
	@echo "  status     Check system dependencies"
	@echo "  test       Run test suite"
	@echo "  transform  Load a ShinyExport JSON or CSV snapshot into data/products.db (default: the single file in input/, or INPUT_PATH=path/to.json|csv)"
	@echo "  build      Materialize data/products_public.db, redacted per sensitive_fields.json (ADR-04)"
	@echo "  explore    Open the transformed SQLite file in Datasette (default data/products.db, override with DB_PATH=path/to.db). Prints a --root URL: visit it to get write access to products_overrides (ADR-09); products itself stays read-only."
	@echo ""

DB_PATH ?= data/products.db
SOURCE_TABLE ?= products_merged

setup:
	@source ./make.sh && setup_commands

status:
	@source ./make.sh && show_status

test:
	pipenv run python -m pytest tests/

transform:
	pipenv run python -m app.transform $(INPUT_PATH)

build:
	pipenv run python -m app.build --source-table $(SOURCE_TABLE)

explore:
	pipenv run datasette $(DB_PATH) -c datasette.yaml --root
