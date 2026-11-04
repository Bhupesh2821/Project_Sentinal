#!/bin/zsh
set -eu
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
source "$PROJECT_DIR/runtime-env.sh"
if [[ ! -x .venv/bin/python ]]; then
  print "Run install.command once, then reopen demo.command."
  exit 1
fi
exec .venv/bin/python main.py --demo "$@"
