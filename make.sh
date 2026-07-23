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
