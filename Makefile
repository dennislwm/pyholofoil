.PHONY: help setup status test check-pins explore transform approve build deploy sync-sheets
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
	@echo "  approve    Record the current products.db snapshot as reviewed (data/products.approved), required before build will run (ADR-05, REQ-002)"
	@echo "  build      Materialize data/products_public.db, redacted per sensitive_fields.json (ADR-04)"
	@echo "  deploy     Verify REDACTED_DB_PATH excludes every sensitive_fields.json column (REQ-013), then copy it into DOCS_DIR (default docs/) for CI to upload as a GitHub Pages artifact (ADR-17) -- view it via datasette-lite (ADR-16): https://lite.datasette.io/?url=https://$(GH_PAGES_HOST)/products_public.db"
	@echo "  explore    Open the transformed SQLite file in Datasette (default data/products.db, override with DB_PATH=path/to.db). Prints a --root URL: visit it to get write access to products_overrides (ADR-09); products itself stays read-only."
	@echo "  sync-sheets  Push products_merged (full data, including sensitive fields -- this is the live artifact, not the redacted one) to a Google Sheet via gws (ADR-14). Requires SPREADSHEET_ID, GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE (service account key path), and GOOGLE_WORKSPACE_PROJECT_ID (quota/billing project -- may differ from the key file's own project). The Sheet's own sharing settings control who can view it -- same as any personal Google Sheet, not automatically public."
	@echo ""

DB_PATH ?= data/products.db
SOURCE_TABLE ?= products_merged
REDACTED_DB_PATH ?= data/products_public.db
DOCS_DIR ?= docs
GH_PAGES_HOST ?= dennislwm.github.io/pyholofoil

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

approve:
	sqlite3 $(DB_PATH) "SELECT MAX(last_updated) FROM products;" > data/products.approved

build:
	pipenv run python -m app.build --source-table $(SOURCE_TABLE)

explore:
	pipenv run datasette $(DB_PATH) -c datasette.yaml --secret $(DATASETTE_SECRET) --plugins-dir=plugins/ -o

sync-sheets:
	pipenv run python -m app.sync_sheets --db-path $(DB_PATH) --source-table $(SOURCE_TABLE) --spreadsheet-id $(SPREADSHEET_ID)

deploy:
	pipenv run python -m app.build --verify-only --redacted-db-path $(REDACTED_DB_PATH)
	pipenv run python -m app.build --publish-static --redacted-db-path $(REDACTED_DB_PATH) --docs-dir $(DOCS_DIR)
	@echo "View at: https://lite.datasette.io/?url=https://$(GH_PAGES_HOST)/products_public.db"
	@echo "(one-time setup: in repo Settings > Pages, set Source to \"GitHub Actions\" -- ADR-17)"
