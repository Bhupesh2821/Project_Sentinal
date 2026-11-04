#!/bin/zsh
set -eu
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
if [[ ! -x .venv/bin/python ]]; then
  print "SENTINAL needs its local Python environment. Open install.command once, then launch again."
  read -r "?Press Return to close. "
  exit 1
fi
source "$PROJECT_DIR/runtime-env.sh"
exec .venv/bin/python main.py "$@"
