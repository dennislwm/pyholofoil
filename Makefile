.PHONY: help setup status test
SHELL := /bin/bash

help:
	@echo ""
	@echo "=== Targets ==="
	@echo "  help    Show this help"
	@echo "  setup   pipenv install from Pipfile"
	@echo "  status  Check system dependencies"
	@echo "  test    Run test suite"
	@echo ""

setup:
	@source ./make.sh && setup_commands

status:
	@source ./make.sh && show_status

test:
	pipenv run pytest tests/
