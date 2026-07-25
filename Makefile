.PHONY: help setup status test check-pins explore transform build deploy
SHELL := /bin/bash

help:
	@echo ""
	@echo "=== Targets ==="
	@echo "  help       Show this help"
	@echo "  setup      pipenv install from Pipfile"
	@echo "  status     Check system dependencies"
	@echo "  test       Run test suite"
	@echo "  check-pins Fail if any Pipfile package is unpinned (bare \"*\")"
	@echo "  transform  Load a ShinyExport JSON or CSV snapshot into data/products.db (default: the single file in input/, or INPUT_PATH=path/to.json|csv)"
	@echo "  build      Materialize data/products_public.db, redacted per sensitive_fields.json (ADR-04)"
	@echo "  deploy     Publish data/products_public.db to Vercel via datasette-publish-vercel (ADR-12) -- no datasette.yaml applied, products_overrides doesn't exist in this artifact"
	@echo "  explore    Open the transformed SQLite file in Datasette (default data/products.db, override with DB_PATH=path/to.db). Prints a --root URL: visit it to get write access to products_overrides (ADR-09); products itself stays read-only."
	@echo ""

DB_PATH ?= data/products.db
SOURCE_TABLE ?= products_merged
REDACTED_DB_PATH ?= data/products_public.db
VERCEL_PROJECT ?= pyholofoil-public

setup:
	@source ./make.sh && setup_commands

status:
	@source ./make.sh && show_status

test:
	pipenv run python -m pytest tests/

check-pins:
	@! grep -n '= "\*"' Pipfile

transform:
	pipenv run python -m app.transform $(INPUT_PATH)

build:
	pipenv run python -m app.build --source-table $(SOURCE_TABLE)

explore:
	pipenv run datasette $(DB_PATH) -c datasette.yaml --root

deploy:
	pipenv run datasette publish vercel $(REDACTED_DB_PATH) --project=$(VERCEL_PROJECT)
