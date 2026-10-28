#!/bin/zsh
set -eu
umask 077
SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
cd "$PROJECT_DIR"
if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
fi
PYTHON_BIN="${1:-python3}"
SERVICE_MODE="${2:-mock}"
exec "$PYTHON_BIN" -m server.app --mode "$SERVICE_MODE"
