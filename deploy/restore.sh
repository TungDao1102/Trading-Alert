#!/usr/bin/env bash
set -Eeuo pipefail
# Restore the latest verified off-host snapshot onto an EMPTY host (13.1-10, D-13).
#
# Usage:
#   deploy/restore.sh [--snapshot ID] [--force] [--no-start] [--dry-run]
#
# Order: start only postgres; pull the snapshot (newest, or --snapshot ID) into a fresh directory
# data/backup/restore-<UTC timestamp>; run the refusing restore (bundle verification, empty-target
# checks, pg_restore, Parquet copy, alembic upgrade head); then start the whole stack unless
# --no-start. --force is forwarded to the restore (allows a non-empty target; files are never
# overwritten). A failing step stops the script with that step's exit code.
#
# The wrapper holds no restore logic: every step is `python -m src.ops.backup <subcommand>` in the
# compose ops image. Backup credentials (BACKUP_S3_*, BACKUP_CRYPT_*) come from the env file;
# COMPOSE_PROJECT_NAME and TRADING_ENV_FILE are honoured from the environment.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

# Git Bash on Windows would otherwise rewrite container paths such as /app/data/backup.
export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PY=/app/.venv/bin/python

SNAPSHOT=""
FORCE=0
NO_START=0
COMPOSE=()

usage() {
  sed -n '3,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
}

usage_error() {
  usage
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --snapshot)
        (($# >= 2)) || usage_error "option --snapshot needs a value"
        SNAPSHOT="$2"
        shift
        ;;
      --force) FORCE=1 ;;
      --no-start) NO_START=1 ;;
      --dry-run) DRY_RUN=1 ;;
      -h | --help)
        usage
        exit 0
        ;;
      *) usage_error "unknown option: $1" ;;
    esac
    shift
  done
  if [[ -n $SNAPSHOT && ! $SNAPSHOT =~ ^[0-9]{8}T[0-9]{6}Z$ ]]; then
    usage_error "--snapshot must look like 20260930T031500Z"
  fi
}

# ops_run ARGS...: one python subcommand in the ops service (postgres is already up).
ops_run() {
  run "${COMPOSE[@]}" --profile ops run --rm -T --no-deps ops "$PY" -m src.ops.backup "$@"
}

main() {
  parse_args "$@"
  export DRY_RUN
  cd "$REPO_ROOT"
  compose_init
  local stamp dest pull_args restore_args
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dest="data/backup/restore-$stamp"
  pull_args=(pull --dest "$dest")
  if [[ -n $SNAPSHOT ]]; then
    pull_args+=(--snapshot "$SNAPSHOT")
  fi
  restore_args=(restore --bundle-root "$dest" --parquet-target data/raw)
  if ((FORCE)); then
    restore_args+=(--force)
  fi

  run "${COMPOSE[@]}" up -d --wait --wait-timeout 180 postgres
  ops_run "${pull_args[@]}"
  ops_run "${restore_args[@]}"
  if ((NO_START)); then
    log "restore finished; the stack was not started (--no-start)"
    return 0
  fi
  run "${COMPOSE[@]}" up -d
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
