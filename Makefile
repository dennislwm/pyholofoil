.PHONY: help setup status test check-pins explore transform approve build deploy sync-sheets
SHELL := /bin/bash

help:
	@echo ""
	@echo "Workflow: setup -> transform -> explore (side-loop, as needed) -> approve -> build -> deploy"
	@echo "Parallel branch: sync-sheets (off transform's output, independent of build/deploy)"
	@echo ""
	@echo "=== Targets ==="
	@echo "  help         Show this help"
	@echo "  setup        pipenv install from Pipfile"
	@echo "  status       Check system dependencies"
	@echo "  test         Run test suite"
	@echo "  check-pins   Fail if any Pipfile package is unpinned"
	@echo "  transform    Load a ShinyExport JSON/CSV into data/products.db"
	@echo "               INPUT_PATH: single file in input/"
	@for f in $(INPUT_FILES); do echo "               INPUT_PATH: $$f"; done
	@echo "  approve      Record products.db snapshot as reviewed (required before build)"
	@echo "               DB_PATH: data/products.db"
	@for f in $(DATA_DBS); do echo "               DB_PATH: $$f"; done
	@echo "  build        Materialize data/products_public.db, redacted per redaction.yaml"
	@echo "               SOURCE_TABLE: products_merged"
	@for t in $(OVERRIDES_TABLES); do echo "               SOURCE_TABLE: $$t"; done
	@echo "  deploy       Copy the redacted DB into DOCS_DIR for CI to publish"
	@echo "               REDACTED_DB_PATH: data/products_public.db"
	@echo "               DOCS_DIR: docs"
	@echo "  explore      Open the transformed SQLite file in Datasette"
	@echo "               DB_PATH: data/products.db"
	@for f in $(DATA_DBS); do echo "               DB_PATH: $$f"; done
	@echo "               run 'source make.sh && load_datasette_env' first (local only; CI sets it as a repo variable)"
	@echo "  sync-sheets  Push full products_merged data to a Google Sheet via gws"
	@echo "               DB_PATH: data/products.db"
	@for f in $(DATA_DBS); do echo "               DB_PATH: $$f"; done
	@echo "               SOURCE_TABLE: products_merged"
	@for t in $(OVERRIDES_TABLES); do echo "               SOURCE_TABLE: $$t"; done
	@echo "               SPREADSHEET_ID: required, no default"
	@echo "               run 'source make.sh && load_gws_env' first (local only; CI sets it as a repo variable)"
	@echo ""

DB_PATH ?= data/products.db
SOURCE_TABLE ?= products_merged
REDACTED_DB_PATH ?= data/products_public.db
DOCS_DIR ?= docs
GH_PAGES_HOST ?= dennislwm.github.io/pyholofoil
OVERRIDES_TABLES := $(shell awk '/^x-overrides-tables:/{f=1;next} f&&/^- /{print "products_merged_" substr($$0,3)} f&&!/^- /{f=0}' datasette.yaml)
INPUT_FILES := $(shell ls input/ 2>/dev/null)
DATA_DBS := $(shell ls data/*.db 2>/dev/null | grep -v '^$(DB_PATH)$$')

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
	pipenv run python -m app.transform --merge-only
	pipenv run datasette $(DB_PATH) -c datasette.yaml --secret $(DATASETTE_SECRET) --plugins-dir=plugins/ -o

sync-sheets:
	pipenv run python -m app.sync_sheets --db-path $(DB_PATH) --source-table $(SOURCE_TABLE) --spreadsheet-id $(SPREADSHEET_ID)

deploy:
	pipenv run python -m app.build --verify-only --redacted-db-path $(REDACTED_DB_PATH)
	pipenv run python -m app.build --publish-static --redacted-db-path $(REDACTED_DB_PATH) --docs-dir $(DOCS_DIR)
	@echo "View at: https://lite.datasette.io/?url=https://$(GH_PAGES_HOST)/products_public.db"
	@echo "(one-time setup: in repo Settings > Pages, set Source to \"GitHub Actions\" -- ADR-17)"
