# pyholofoil

Trading-card asset data pipeline. See [pyholofoil.wiki](../13pyholofoil.wiki) for requirements and decisions.

## Setup: CI deploy pipeline ([ADR-13](../13pyholofoil.wiki/decisions/adr-13-deploy-cadence-mechanism.md), [ADR-16](../13pyholofoil.wiki/decisions/adr-16-public-copy-truly-static.md), [ADR-17](../13pyholofoil.wiki/decisions/adr-17-static-artifact-reaches-pages.md))

One-time steps so `deploy.yml` actually has somewhere to run and somewhere to publish.

1. **Register a self-hosted runner** → repo Settings → Actions → Runners → New self-hosted runner → pick macOS + your architecture → run the provided `./config.sh` (one-time, time-limited registration token) then `./run.sh`, kept running. `deploy.yml` targets `runs-on: [self-hosted, macOS]`; without this, every push to `main` queues a job with nothing to run it.
2. **Enable GitHub Pages via Actions** → repo Settings → Pages → Source → **GitHub Actions** (not "Deploy from a branch"). `deploy.yml` publishes `docs/products_public.db` via `actions/upload-pages-artifact` + `actions/deploy-pages`; `docs/` is gitignored and never committed, so the branch-serving option has nothing to find.

## Usage: declaring an extra overrides table ([ADR-20](../13pyholofoil.wiki/decisions/adr-20-multiple-overrides-tables.md))

Not a one-time setup step -- repeat this whenever you want another independent correction set against `products`, e.g. a second reviewer.

1. Add the table's name to `datasette.yaml`'s `x-overrides-tables` list (create the key if it doesn't exist yet):
   ```yaml
   x-overrides-tables:
     - reviewer_b
   ```
2. Run `make transform` (or `python -m app.transform`). This creates `products_overrides_reviewer_b` and `products_merged_reviewer_b`, and generates a `copy-to-overrides-reviewer_b` canned write-query in `datasette.yaml` -- gives that table the same one-click "copy from products" convenience the primary table has, via `make explore`'s write-UI.
3. If `explore` is already running, restart it -- `datasette.yaml` is only read at Datasette startup.
4. To remove a declared table, delete its entry from `x-overrides-tables` and run `make transform` again -- the generated canned query is cleaned up automatically. **The underlying `products_overrides_<name>`/`products_merged_<name>` table and view are NOT dropped** -- only the canned query goes away. Undeclaring a table never destroys its data; re-declaring the same name later picks the existing table back up.

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
