#!/bin/zsh
set -eu
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
source "$PROJECT_DIR/runtime-env.sh"
export SENTINAL_TEST_VIDEO="$PROJECT_DIR/tests/fixtures/vtest.avi"
exec .venv/bin/python -m pytest tests "$@" --basetemp "$PROJECT_DIR/work/tmp/pytest"
