.PHONY: help setup status test explore transform
SHELL := /bin/bash

help:
	@echo ""
	@echo "=== Targets ==="
	@echo "  help       Show this help"
	@echo "  setup      pipenv install from Pipfile"
	@echo "  status     Check system dependencies"
	@echo "  test       Run test suite"
	@echo "  transform  Load a ShinyExport JSON snapshot into data/products.db (JSON_PATH=path/to.json SNAPSHOT_DATE=YYYYMMDD)"
	@echo "  explore    Open the transformed SQLite file in Datasette (DB_PATH=path/to.db)"
	@echo ""

setup:
	@source ./make.sh && setup_commands

status:
	@source ./make.sh && show_status

test:
	pipenv run python -m pytest tests/

transform:
	pipenv run python -m app.transform $(JSON_PATH) $(SNAPSHOT_DATE)

explore:
	pipenv run datasette $(DB_PATH)
