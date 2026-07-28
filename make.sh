function check_pipenv {
  command -v pipenv > /dev/null 2>&1 || { echo "[ERROR][$FUNCNAME]: pipenv not installed."; return 1; }
  echo "[OK]   pipenv found ($(pipenv --version 2>&1))"
}

function check_venv {
  pipenv --venv > /dev/null 2>&1 || { echo "[WARN][$FUNCNAME]: venv not ready -- run make setup"; return 0; }
  echo "[OK]   venv ready ($(pipenv --venv 2>&1))"
}

function setup_pipenv {
  pipenv install
}

function show_status {
  echo ""
  echo "=== Status ==="
  check_pipenv || true
  check_venv || true
  echo "=============="
  echo ""
}

function setup_commands {
  echo "=== pyholofoil Setup ==="
  check_pipenv
  setup_pipenv
  echo "========================"
}

function load_gws_env {
  lpass status > /dev/null 2>&1 || { echo "[ERROR][$FUNCNAME]: not logged into lpass -- run 'lpass login <email>' first."; return 1; }

  local cred_file="$HOME/.config/gws/service-account.json"
  if [ ! -f "$cred_file" ]; then
    mkdir -p "$(dirname "$cred_file")"
    lpass show --notes "global/google-sa-gws-json" > "$cred_file"
    chmod 400 "$cred_file"
    echo "[OK]   created $cred_file"
  fi

  export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE="$cred_file"
  export GOOGLE_WORKSPACE_PROJECT_ID="$(lpass show --notes "pyholofoil/env" | grep '^GWS_PROJECT_ID=' | cut -d= -f2-)"
  export SPREADSHEET_ID="$(lpass show --notes "pyholofoil/env" | grep '^GWS_DEV_SHEET_ID=' | cut -d= -f2-)"

  if [ -z "$GOOGLE_WORKSPACE_PROJECT_ID" ] || [ -z "$SPREADSHEET_ID" ]; then
    echo "[WARN][$FUNCNAME]: one or more values came back empty -- check pyholofoil/env note."
    return 1
  fi
  echo "[OK]   gws env exported"
}

function load_datasette_env {
  lpass status > /dev/null 2>&1 || { echo "[ERROR][$FUNCNAME]: not logged into lpass -- run 'lpass login <email>' first."; return 1; }

  export DATASETTE_SECRET="$(lpass show --notes "pyholofoil/env" | grep '^DATASETTE_SECRET=' | cut -d= -f2-)"
  export DATASETTE_OPERATOR_PASSWORD_HASH="$(lpass show --notes "pyholofoil/env" | grep '^DATASETTE_OPERATOR_PASSWORD_HASH=' | cut -d= -f2-)"

  if [ -z "$DATASETTE_SECRET" ] || [ -z "$DATASETTE_OPERATOR_PASSWORD_HASH" ]; then
    echo "[WARN][$FUNCNAME]: one or more values came back empty -- check pyholofoil/env note."
    return 1
  fi
  echo "[OK]   datasette env exported"
}

function verify_gws {
  gws sheets spreadsheets get --params "{\"spreadsheetId\": \"$SPREADSHEET_ID\"}" > /dev/null \
    && echo "[OK]   gws auth verified against $SPREADSHEET_ID" \
    || { echo "[ERROR][$FUNCNAME]: gws call failed -- check credentials/project/sheet-id/sharing."; return 1; }
}
