# pyholofoil

Trading-card asset data pipeline. See [pyholofoil.wiki](../13pyholofoil.wiki) for requirements and decisions.

## Setup: CI deploy pipeline ([ADR-13](../13pyholofoil.wiki/decisions/adr-13-deploy-cadence-mechanism.md), [ADR-16](../13pyholofoil.wiki/decisions/adr-16-public-copy-truly-static.md), [ADR-17](../13pyholofoil.wiki/decisions/adr-17-static-artifact-reaches-pages.md))

One-time steps so `deploy.yml` actually has somewhere to run and somewhere to publish.

1. **Register a self-hosted runner** → repo Settings → Actions → Runners → New self-hosted runner → pick macOS + your architecture → run the provided `./config.sh` (one-time, time-limited registration token) then `./run.sh`, kept running. `deploy.yml` targets `runs-on: [self-hosted, macOS]`; without this, every push to `main` queues a job with nothing to run it.
2. **Enable GitHub Pages via Actions** → repo Settings → Pages → Source → **GitHub Actions** (not "Deploy from a branch"). `deploy.yml` publishes `docs/products_public.db` via `actions/upload-pages-artifact` + `actions/deploy-pages`; `docs/` is gitignored and never committed, so the branch-serving option has nothing to find.

## Setup: redacting sensitive fields ([ADR-04](../13pyholofoil.wiki/decisions/adr-04-build-stage-split-mechanism.md), REQ-013, REQ-018)

`sensitive_fields.json` is a manual, operator-edited list of column names that must never reach the public/redacted artifact -- nothing populates it automatically. `make build`'s `verify_redacted()` step refuses to run (and CI's `deploy.yml` refuses to publish) if any listed column is still present in the redacted db, so this file is what actually keeps cost/pricing data (`paid_total`, `paid_per_unit`, `paid_currency`) and anything else you add out of the public static copy.

1. Edit `sensitive_fields.json` directly -- a flat JSON array of column names, e.g. `["paid_total", "paid_per_unit", "paid_currency"]`.
2. Run `make build`. `build_redacted()` excludes every listed column from the redacted artifact; `verify_redacted()` then re-checks the result and fails loudly if any of them are still present, catching a stale or misconfigured artifact before it can reach `make deploy`.
3. An empty list (the default) excludes nothing -- every column, including cost/pricing data, ships to the public copy verbatim until you populate this file.

## Setup: operator login ([ADR-26](../13pyholofoil.wiki/decisions/adr-26-root-bypasses-products-readonly-lock.md))

One-time steps so `make explore` has a real, scoped `operator` identity instead of Datasette's unrestricted `root` superuser -- `root` bypasses every write permission unconditionally, so `products`'s read-only lock was never actually enforced against it.

1. **Generate a password hash**: `pipenv run datasette hash-password` (interactive) or `echo 'your password' | pipenv run datasette hash-password --no-confirm`.
2. **Generate a Datasette secret**: any random string, e.g. `python3 -c "import secrets; print(secrets.token_hex(32))"`.
3. **Store both, one command** (same `pyholofoil/env` note the Google Sheets setup already uses):
   ```bash
   echo -e "DATASETTE_SECRET=<value from step 2>\nDATASETTE_OPERATOR_PASSWORD_HASH=<value from step 1>" | lpass add --non-interactive --notes "pyholofoil/env"
   ```
4. **Run once per new terminal**: `source make.sh && load_datasette_env` -- exports both as env vars for `make explore` to read.

## Usage: correcting a data error ([ADR-09](../13pyholofoil.wiki/decisions/adr-09-explore-stage-write-capability.md), REQ-010, [ADR-26](../13pyholofoil.wiki/decisions/adr-26-root-bypasses-products-readonly-lock.md))

1. Run `make explore` (after the one-time Setup above). It opens a login page in your browser -- log in as `operator` with the password from Setup step 1. Without this you're browsing anonymously: `products` is explicitly locked read-only in `datasette.yaml`, and `products_overrides` only grants write access to `operator`, so the write-UI's Edit/Insert buttons won't work. The login cookie persists across `make explore` restarts as long as the browser stays open (no expiry is set on it) -- only fully closing the browser forces logging in again.
2. Open the `copy-to-overrides` canned query (Queries page) and submit the product's `id`. This copies that row into `products_overrides`, all columns NULL except what was copied -- `products` itself is never written to.
3. You're redirected to `products_overrides` -- click **Edit** on the copied row (via `datasette-write-ui`) and correct the fields you need. The correction persists across future `transform` re-runs.
4. `SOURCE_TABLE` (Makefile variable, default `products_merged`) is what `build` and `sync-sheets` both read from, so a correction in `products_overrides` flows through automatically to `make build`'s public artifact and `make sync-sheets`'s Sheet push. Override it (e.g. `make build SOURCE_TABLE=products_merged_reviewer_b`) to source from a declared extra overrides table (ADR-20) instead of the primary one.

## Usage: declaring an extra overrides table ([ADR-20](../13pyholofoil.wiki/decisions/adr-20-multiple-overrides-tables.md))

Not a one-time setup step -- repeat this whenever you want another independent correction set against `products`, e.g. a second reviewer.

1. Add the table's name to `datasette.yaml`'s `x-overrides-tables` list (create the key if it doesn't exist yet):
   ```yaml
   x-overrides-tables:
     - reviewer_b
   ```
2. Run `make transform` (or `python -m app.transform`). This creates `products_overrides_reviewer_b` and `products_merged_reviewer_b`, and generates a `copy-to-overrides-reviewer_b` canned write-query in `datasette.yaml` -- gives that table the same one-click "copy from products" convenience the primary table has, via `make explore`'s write-UI.
3. If `explore` is already running, no restart needed for the new table or its canned query -- both are picked up live ([ADR-25](../13pyholofoil.wiki/decisions/adr-25-config-change-needs-no-restart.md)). A restart is only needed if you also want to grant the new table write permissions (a `tables.products_overrides_reviewer_b.permissions` block, not generated automatically -- add it by hand, matching the shape REQ-023 added for the primary table).
4. To remove a declared table, delete its entry from `x-overrides-tables` and run `make transform` again -- the generated canned query is cleaned up automatically. **The underlying `products_overrides_<name>`/`products_merged_<name>` table and view are NOT dropped** -- only the canned query goes away. Undeclaring a table never destroys its data; re-declaring the same name later picks the existing table back up.

## Usage: declaring an extra override-only column ([ADR-10](../13pyholofoil.wiki/decisions/adr-10-overrides-view-schema-sync.md), scoped per table by [ADR-22](../13pyholofoil.wiki/decisions/adr-22-per-table-extra-columns-scope.md))

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
   A column declared under one table is never applied to another -- each table's list is independent.
2. Run `make transform` (or `python -m app.transform`). This adds the column to that one table via `ALTER TABLE`, defaulting existing rows to `''` (not `NULL` -- `datasette-write-ui`'s edit form errors on a `NULL`-valued field), and rebuilds that table's merged view to include it.
3. If `explore` is already running, no restart needed -- Datasette reads table columns live from the database on every request, not from a startup snapshot.
4. Adding a column via `datasette-edit-schema`'s own schema-editing UI instead of this config list works too, but existing rows are left `NULL` (no default-value option in that UI) -- backfill them yourself (`UPDATE <table> SET <col> = '' WHERE <col> IS NULL`) before editing any row through the write-UI, or the same `NULL`-crashes-the-edit-form error applies. Prefer this config-declared route: it survives a schema-recovery rebuild (ADR-08) and a fresh checkout; an ad hoc UI-added column doesn't.

## Setup: Google Sheets sync ([ADR-14](../13pyholofoil.wiki/decisions/adr-14-live-artifact-remote-access.md))

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
7. **Run once per new terminal** -- creates the credential file on first run, exports all three env vars, verifies the whole chain against the real Sheet:
   ```bash
   source make.sh && load_gws_env && verify_gws
   ```
8. **Set three repo variables** → `github.com/dennislwm/pyholofoil/settings/variables/actions` (CI can't read your LastPass):
   - `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` = the path from step 7
   - `SPREADSHEET_ID` = the ID from step 5
   - `GOOGLE_WORKSPACE_PROJECT_ID` = the project ID from step 3 -- required even when it matches the key file's own project. Verified live: omitting it fails with `Project 'projects/<wrong-id>' not found or deleted` or a `serviceusage.services.use` permission error.
