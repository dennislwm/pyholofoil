.PHONY: help setup status test explore transform build
SHELL := /bin/bash

help:
	@echo ""
	@echo "=== Targets ==="
	@echo "  help       Show this help"
	@echo "  setup      pipenv install from Pipfile"
	@echo "  status     Check system dependencies"
	@echo "  test       Run test suite"
	@echo "  transform  Load a ShinyExport JSON snapshot into data/products.db (JSON_PATH=path/to.json SNAPSHOT_DATE=YYYYMMDD)"
	@echo "  build      Materialize data/products_public.db, redacted per sensitive_fields.json (ADR-04)"
	@echo "  explore    Open the transformed SQLite file in Datasette (default data/products.db, override with DB_PATH=path/to.db)"
	@echo ""

DB_PATH ?= data/products.db

setup:
	@source ./make.sh && setup_commands

status:
	@source ./make.sh && show_status

test:
	pipenv run python -m pytest tests/

transform:
	pipenv run python -m app.transform $(JSON_PATH) $(SNAPSHOT_DATE)

build:
	pipenv run python -m app.build

explore:
	pipenv run datasette $(DB_PATH)
