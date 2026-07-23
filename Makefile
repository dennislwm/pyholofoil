.PHONY: help setup status test explore
SHELL := /bin/bash

help:
	@echo ""
	@echo "=== Targets ==="
	@echo "  help     Show this help"
	@echo "  setup    pipenv install from Pipfile"
	@echo "  status   Check system dependencies"
	@echo "  test     Run test suite"
	@echo "  explore  Open the transformed SQLite file in Datasette (DB_PATH=path/to.db)"
	@echo ""

setup:
	@source ./make.sh && setup_commands

status:
	@source ./make.sh && show_status

test:
	pipenv run python -m pytest tests/

explore:
	pipenv run datasette $(DB_PATH)
