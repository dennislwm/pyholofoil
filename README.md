# pyholofoil

Trading-card asset data pipeline. See [pyholofoil.wiki](../13pyholofoil.wiki) for requirements and decisions.

## Workflow

The pipeline runs as a straight line, `transform` → `explore` → `build` → `deploy`, with `sync-sheets` as a parallel branch off the same data. `explore` is the one exception -- see step 3.

1. **`make setup`** -- installs dependencies (`pipenv install`). Nothing else runs without this.
2. **`make transform`** -- loads a ShinyExport JSON/CSV snapshot into `data/products.db`. The pipeline's only input step; every later stage reads from the database this produces. Every export is treated as a full inventory snapshot: any `id` absent from the loaded file is deleted from `products`. Back up `data/products.db` first if you want to keep a copy of rows about to disappear.
3. **`make explore`** -- opens the database in Datasette to browse and correct data errors. Requires [operator login](#setup-operator-login) set up first, or login fails. **Out of band**: unlike the other steps, this isn't run once per pipeline pass -- it's a side-loop you enter whenever a data error needs fixing, as many times as needed, independent of when you last ran `transform`. See [correcting a data error](#usage-correcting-a-data-error).
4. **`make build`** -- materializes `data/products_public.db`, a redacted copy with `redaction.yaml`'s columns stripped and only rows matching its `rows` filter kept (REQ-032). Requires [a reviewed, approved snapshot](#usage-approving-a-reviewed-snapshot) -- refuses with `No approval on record` otherwise. Also requires [redaction config populated](#setup-redacting-sensitive-fields) -- an empty list ships everything unredacted and unfiltered.
5. **`make deploy`**:
   - Verifies the redacted build actually excludes every sensitive field.
   - Only then publishes it for CI to upload as a public GitHub Pages artifact, viewable via datasette-lite.
   - `build` alone doesn't ship anything; this is the actual publish step, gated on the verify check so a misconfigured redaction can't reach the public copy.

**Parallel branch**: `make sync-sheets` pushes the full (non-redacted) merged data to a Google Sheet -- a separate, optional distribution channel from the public static copy. Requires [Google Sheets sync setup](#setup-google-sheets-sync) first, or the command errors on missing env vars.

**Supporting commands**: `make test` (test suite), `make check-pins` (fails if any `Pipfile` package is unpinned), `make status` (checks system dependencies) -- run these as needed, not part of the main flow.

## Usage: correcting a data error

*Related: ADR-09, REQ-010, ADR-26*

1. Run `make explore` (after the one-time [operator login setup](#setup-operator-login) below):
   - Opens a login page in your browser -- log in as `operator` with the password from that setup's step 1.
   - Without this you're browsing anonymously: `products` is explicitly locked read-only in `datasette.yaml`, and `products_overrides` only grants write access to `operator`, so the write-UI's Edit/Insert buttons won't work.
   - The login cookie persists across `make explore` restarts as long as the browser stays open (no expiry is set on it) -- only fully closing the browser forces logging in again.
2. Open the `copy-to-overrides` canned query (Queries page) and submit the product's `id`. This copies that row into `products_overrides`, all columns NULL except what was copied -- `products` itself is never written to.
3. You're redirected to `products_overrides` -- click **Edit** on the copied row (via `datasette-write-ui`) and correct the fields you need. The correction persists across future `transform` re-runs.
4. `SOURCE_TABLE` (Makefile variable, default `products_merged`) is what `build` and `sync-sheets` both read from, so a correction in `products_overrides` flows through automatically to `make build`'s public artifact and `make sync-sheets`'s Sheet push. Override it (e.g. `make build SOURCE_TABLE=products_merged_reviewer_b`) to source from a declared extra overrides table (ADR-20) instead of the primary one.

## Usage: approving a reviewed snapshot

*Related: ADR-05, REQ-002, REQ-031*

`make build` refuses to run until someone has actually looked at the data -- it checks `data/products.approved` against the live `products` table and errors (`No approval on record`) if the file is missing or stale.

1. Review the data via `make explore` (see [Usage: correcting a data error](#usage-correcting-a-data-error) above).
2. Once satisfied, run `make approve`. It records the current snapshot (`MAX(last_updated)` in `products`) into `data/products.approved` -- silent, no confirmation output.
3. `make build` now proceeds. Any subsequent `make transform` that changes data invalidates the approval automatically (the recorded value no longer matches) -- no separate "expire" step, just rerun `make approve` after reviewing again.

`data/products.approved` is gitignored, local-only, and holds no history -- one file, one current value, overwritten each approval. It records *that* a snapshot was reviewed, not *who* or *when*.

## Usage: declaring an extra overrides table

*Related: ADR-20*

Not a one-time setup step -- repeat this whenever you want another independent correction set against `products`, e.g. a second reviewer.

1. Add the table's name to `datasette.yaml`'s `x-overrides-tables` list (create the key if it doesn't exist yet):
   ```yaml
   x-overrides-tables:
     - reviewer_b
   ```
2. Run `make transform` (or `python -m app.transform`):
   - Creates `products_overrides_reviewer_b` and `products_merged_reviewer_b`.
   - Generates a `copy-to-overrides-reviewer_b` canned write-query in `datasette.yaml` -- gives that table the same one-click "copy from products" convenience the primary table has, via `make explore`'s write-UI.
3. If `explore` is already running:
   - No restart needed for the new table or its canned query -- both are picked up live (ADR-25).
   - A restart is only needed if you also want to grant the new table write permissions (a `tables.products_overrides_reviewer_b.permissions` block, not generated automatically -- add it by hand, matching the shape REQ-023 added for the primary table).
4. To remove a declared table: delete its entry from `x-overrides-tables`, then run `make transform` again:
   - The generated canned query is cleaned up automatically.
   - **The underlying `products_overrides_<name>`/`products_merged_<name>` table and view are NOT dropped** -- only the canned query goes away.
   - Undeclaring a table never destroys its data; re-declaring the same name later picks the existing table back up.

## Usage: declaring an extra override-only column

*Related: ADR-10, ADR-22*

Not a one-time setup step -- repeat whenever a correction needs a field `products` doesn't have (e.g. `sold_remarks`).

1. Add the column's name under that overrides table's own `x-overrides-extra-columns` list, nested under `databases.products.tables.<table_name>` (create the key path if it doesn't exist yet). For the primary table, `<table_name>` is `products_overrides`; for a table declared via `x-overrides-tables` (ADR-20), it's `products_overrides_<name>`:
   ```yaml
   databases:
     products:
       tables:
         products_overrides_sold:
           x-overrides-extra-columns:
           - sold_remarks
   ```
   - A column declared under one table is never applied to another -- each table's list is independent.
2. Run `make transform` (or `python -m app.transform`):
   - Adds the column to that one table via `ALTER TABLE`, defaulting existing rows to `''` (not `NULL` -- `datasette-write-ui`'s edit form errors on a `NULL`-valued field).
   - Rebuilds that table's merged view to include it.
3. If `explore` is already running, no restart needed -- Datasette reads table columns live from the database on every request, not from a startup snapshot.
4. Adding a column via `datasette-edit-schema`'s own schema-editing UI instead of this config list works too, but:
   - Existing rows are left `NULL` (no default-value option in that UI), and the same `NULL`-crashes-the-edit-form error applies until backfilled. Once the column is also added to `x-overrides-extra-columns` (step 1) and `make transform` has run (step 2), a matching `backfill-null-extra-columns-<table_name>` canned query is generated automatically -- run it once from that table's page to clear every `NULL` to `''`.
   - Prefer the config-declared route instead: it survives a schema-recovery rebuild (ADR-08) and a fresh checkout; an ad hoc UI-added column doesn't.

## Maintainer setup

One-time infra/ops setup, not part of the day-to-day operator workflow above.

### Setup: operator login

*Related: ADR-26*

One-time steps so `make explore` has a real, scoped `operator` identity instead of Datasette's unrestricted `root` superuser -- `root` bypasses every write permission unconditionally, so `products`'s read-only lock was never actually enforced against it.

1. **Generate a password hash**: `HASH=$(pipenv run datasette hash-password --no-confirm <<< 'your password')`.
2. **Generate a Datasette secret**: `SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")`.
3. **Store both, one command** (same `pyholofoil/env` note the Google Sheets setup already uses; keep the hash/secret in variables rather than pasting them literally -- the hash's own `$` delimiters get silently stripped inside a double-quoted string otherwise):
   ```bash
   echo -e "DATASETTE_SECRET=$SECRET\nDATASETTE_OPERATOR_PASSWORD_HASH=$HASH" | lpass add --non-interactive --notes "pyholofoil/env"
   ```
4. **Run once per new terminal**: `source make.sh && load_datasette_env` -- exports both as env vars for `make explore` to read.

### Setup: MCP-connected ad hoc queries

*Related: ADR-28*

One-time step so an MCP client (e.g. Claude Code) can ask ad hoc natural-language questions against the live database instead of hand-writing SQL. `datasette-mcp` adds a read-only `/-/mcp` endpoint to the same `make explore` process -- no separate server, no extra port.

1. With `make explore` running, register the endpoint once per client: `claude mcp add --transport http --scope local datasette http://localhost:8001/-/mcp`.
2. The MCP session inherits whatever actor is logged into that browser session (`operator`, per [Setup: operator login](#setup-operator-login) above) -- `list_databases`/`get_database_schema`/`execute_sql` are gated by the same `execute-sql`/table permissions as everywhere else, and only ever read: no write tool exists in the plugin.
3. This is a default-tool preference, not a permission boundary -- an MCP client with local shell access to this repo can still write to the database directly (e.g. via `sqlite3`); adopting MCP only makes the read-only path the habitual default for ad hoc queries.

### Setup: redacting sensitive fields

*Related: ADR-04, ADR-27, REQ-013, REQ-018*

`redaction.yaml` is a manual, operator-edited list of column names that must never reach the public/redacted artifact -- nothing populates it automatically. A `_global` key applies to every table; a per-table key (the source-table name, e.g. `products_merged_sold`) adds columns redacted only for that table (ADR-27 -- lets tables declared via ADR-20's `x-overrides-tables` carry different sensitive columns from the primary one). `make build`'s `verify_redacted()` step refuses to run (and CI's `deploy.yml` refuses to publish) if any listed column is still present in the redacted db, so this file is what actually keeps cost/pricing data (`paid_total`, `paid_per_unit`, `paid_currency`) and anything else you add out of the public static copy.

Per REQ-032, the same file also filters *rows*: give any key a `rows` WHERE fragment alongside (or instead of) `columns`, and only matching rows reach the public copy. `_global` and a per-table `rows` fragment both apply (combined with `AND`) when both are set. Omitting `rows` keeps every row -- zero behavior change.

1. Edit `redaction.yaml` directly, e.g.:
   ```yaml
   _global:
     columns:
       - paid_total       # cost/purchase-price data
       - paid_per_unit
       - paid_currency
     rows: "rarity = 'Sealed'"  # loose/graded cards never reach the public copy
   products_merged_sold:
     columns:
       - sold_value_total  # sale price, same sensitivity class as paid_*
   ```
   A bare list (no `columns:`/`rows:` keys) still works under any key -- back-compat with the original columns-only shape. YAML comments are supported -- unlike the old flat JSON list, you can record *why* a column is listed.
2. Run `make build`:
   - `build_redacted()` excludes every column listed under `_global` plus the current `--source-table`'s own key from the redacted artifact, and keeps only rows matching every declared `rows` fragment.
   - `verify_redacted()` then re-checks the result against every declared table's columns combined, failing loudly if any are still present -- catching a stale or misconfigured artifact before it can reach `make deploy`. It does not re-check row filtering (which rows apply is determined at build time by `--source-table`; verification only ever checks columns, per ADR-27).
3. An empty `_global: []` (the default) excludes nothing -- every column, including cost/pricing data, ships to the public copy verbatim, and every row passes through, until you populate this file.

### Setup: Google Sheets sync

*Related: ADR-14*

One-time steps to let the CI workflow push the live artifact to a Google Sheet.

1. **Create a service account** → [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials) → Create Credentials → Service Account → download the key JSON. Store it:
   ```bash
   lpass add --non-interactive --notes "global/google-sa-gws-json" < service-account-key.json
   ```
2. **Enable the Sheets API** → [console.cloud.google.com/apis/library](https://console.cloud.google.com/apis/library) → search "Google Sheets API" → Enable.
3. **Grant the service account access** → [console.developers.google.com/iam-admin/iam](https://console.developers.google.com/iam-admin/iam)`?project=<PROJECT_ID>` → find the service account → grant `Service Usage Consumer` (or a custom role with `serviceusage.services.use`). Separate from Sheet sharing in step 4 -- both required. Propagation: a few minutes. Note the project ID for step 6.
4. **Share the target Sheet** → open it → Share → add the service account's email (`...@<project>.iam.gserviceaccount.com`) as **Editor**.
5. **Copy the Sheet ID** from its URL: `docs.google.com/spreadsheets/d/<THIS PART>/edit`.
6. **Store both IDs, one command** (running this twice creates two duplicate notes, not one merged note -- LastPass doesn't upsert by name):
   ```bash
   echo -e "GWS_PROJECT_ID=<id from step 3>\nGWS_DEV_SHEET_ID=<id from step 5>" | lpass add --non-interactive --notes "pyholofoil/env"
   ```
7. **Run once per new terminal**:
   - Creates the credential file on first run.
   - Exports all three env vars.
   - Verifies the whole chain against the real Sheet.
   ```bash
   source make.sh && load_gws_env && verify_gws
   ```
8. **Set three repo variables** → `github.com/dennislwm/pyholofoil/settings/variables/actions` (CI can't read your LastPass):
   - `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` = the path from step 7
   - `SPREADSHEET_ID` = the ID from step 5
   - `GOOGLE_WORKSPACE_PROJECT_ID` = the project ID from step 3 -- required even when it matches the key file's own project. Verified live: omitting it fails with `Project 'projects/<wrong-id>' not found or deleted` or a `serviceusage.services.use` permission error.

### CI deploy pipeline

*Related: ADR-13, ADR-16, ADR-17*

One-time steps so `deploy.yml` actually has somewhere to run and somewhere to publish.

1. **Register a self-hosted runner** → repo Settings → Actions → Runners → New self-hosted runner → pick macOS + your architecture → run the provided `./config.sh` (one-time, time-limited registration token) then `./run.sh`, kept running. `deploy.yml` targets `runs-on: [self-hosted, macOS]`; without this, every push to `main` queues a job with nothing to run it.
2. **Enable GitHub Pages via Actions** → repo Settings → Pages → Source → **GitHub Actions** (not "Deploy from a branch"). `deploy.yml` publishes `docs/products_public.db` via `actions/upload-pages-artifact` + `actions/deploy-pages`; `docs/` is gitignored and never committed, so the branch-serving option has nothing to find.
