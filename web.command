#!/bin/zsh
set -eu
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
source "$PROJECT_DIR/runtime-env.sh"
if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  print 'Run install.command in this folder before starting SENTINAL.'
  exit 2
fi
exec "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/tools/start_command_center.py" "$@"
