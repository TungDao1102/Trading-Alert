#!/usr/bin/env bash
set -Eeuo pipefail
# Linux restore drill (13.1-10, D-13); the counterpart of scripts/backup-drill.ps1 on Windows.
#
# Usage:
#   deploy/backup-drill.sh [--dry-run]
#
# Runs the remote-drill subcommand of `python -m src.ops.backup` in the compose ops image:
# backup, push, pull the snapshot into data/backup/drill-<UTC timestamp>, verify it, restore it into a scratch database
# and compare it with the live one; the scratch database is dropped afterwards. The scratch
# directory is left in place for inspection (remove it by hand). The stack's postgres must be
# running. The exit code is the drill's own. COMPOSE_PROJECT_NAME and TRADING_ENV_FILE are honoured
# from the environment.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

# Git Bash on Windows would otherwise rewrite container paths such as /app/data/backup.
export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PY=/app/.venv/bin/python
COMPOSE=()

usage() {
  sed -n '3,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
}

usage_error() {
  usage
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --dry-run) DRY_RUN=1 ;;
      -h | --help)
        usage
        exit 0
        ;;
      *) usage_error "unknown option: $1" ;;
    esac
    shift
  done
}

main() {
  parse_args "$@"
  export DRY_RUN
  cd "$REPO_ROOT"
  compose_init
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  run "${COMPOSE[@]}" --profile ops run --rm -T --no-deps ops \
    "$PY" -m src.ops.backup drill-remote --scratch-root "data/backup/drill-$stamp"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
