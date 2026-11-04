#!/bin/zsh
set -eu
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
source "$PROJECT_DIR/runtime-env.sh"
if [[ ! -x .venv/bin/python ]]; then
  PYTHON_BIN=""
  for candidate in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 python3.12; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN="$candidate"; break; fi
  done
  if [[ -z "$PYTHON_BIN" ]]; then
    print "Install Python 3.12 from python.org or Homebrew, then run this file again."
    read -r "?Press Return to close. "
    exit 1
  fi
  "$PYTHON_BIN" -m venv .venv
fi
if ! .venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)'; then
  print "This pinned release requires Python 3.12. The existing .venv was preserved."
  print "Keep or rename it inside this project, then create a Python 3.12 environment and rerun install.command."
  exit 1
fi
.venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir -r requirements-lock.txt
.venv/bin/python tools/download_model.py
.venv/bin/python tools/download_everyday_small.py
.venv/bin/python tools/download_extended_model.py
.venv/bin/python tools/download_small_extended_model.py
.venv/bin/python tools/download_v02_models.py
.venv/bin/python -m pip check
print "SENTINAL is installed. Open launch.command to begin."
read -r "?Press Return to close. "
