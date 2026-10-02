#!/usr/bin/env bash
set -Eeuo pipefail
# Scheduled encrypted off-host backup wrapper (13.1-10, D-12, D-13).
#
# Usage:
#   deploy/backup.sh [--dry-run]               run one scheduled backup now
#   deploy/backup.sh --init-remote [--dry-run] first use: stage a bundle, then create the remote
#                                              sentinel on the EMPTY bucket (push --init-remote)
#   deploy/backup.sh --install-timer [--dry-run]
#                                              (root) install trading-backup.service and
#                                              trading-backup.timer (daily 03:15 UTC) and enable it
#
# The wrapper holds no backup, encryption or remote logic: it only calls
# `python -m src.ops.backup <subcommand>` in the compose ops image and returns that command's exit
# code, so a failed backup fails the systemd oneshot service visibly. COMPOSE_PROJECT_NAME and
# TRADING_ENV_FILE are honoured from the environment.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

# Git Bash on Windows would otherwise rewrite container paths such as /app/data/backup.
export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PY=/app/.venv/bin/python
UNIT_TOKEN='@TRADING_DIR@'
UNITS=(trading-backup.service trading-backup.timer)

INIT_REMOTE=0
INSTALL_TIMER=0
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
      --init-remote) INIT_REMOTE=1 ;;
      --install-timer) INSTALL_TIMER=1 ;;
      --dry-run) DRY_RUN=1 ;;
      -h | --help)
        usage
        exit 0
        ;;
      *) usage_error "unknown option: $1" ;;
    esac
    shift
  done
  if ((INIT_REMOTE && INSTALL_TIMER)); then
    usage_error "--init-remote and --install-timer cannot be combined"
  fi
}

# backup_run ARGS...: one python subcommand in the backup service (starts postgres as needed).
backup_run() {
  run "${COMPOSE[@]}" --profile ops run --rm -T backup "$PY" -m src.ops.backup "$@"
}

install_timer() {
  if [[ -z ${TRADING_ROOT_PREFIX:-} && ${EUID} -ne 0 ]]; then
    die "--install-timer must run as root (sudo deploy/backup.sh --install-timer)"
  fi
  [[ $REPO_ROOT != *[[:space:]]* ]] || die "checkout path contains whitespace: $REPO_ROOT"
  local unit_dir content changed=0 unit
  unit_dir="$(p /etc/systemd/system)"
  for unit in "${UNITS[@]}"; do
    [[ -f $SCRIPT_DIR/systemd/$unit ]] || die "missing unit template: deploy/systemd/$unit"
    content="$(<"$SCRIPT_DIR/systemd/$unit")"
    content="${content//"$UNIT_TOKEN"/$REPO_ROOT}"
    write_if_changed "$unit_dir/$unit" "$content"
    if ((WROTE)); then
      changed=1
    fi
  done
  if ((changed)); then
    run systemctl daemon-reload
  fi
  run systemctl enable --now trading-backup.timer
}

main() {
  parse_args "$@"
  export DRY_RUN
  cd "$REPO_ROOT"
  if ((INSTALL_TIMER)); then
    install_timer
    return 0
  fi
  compose_init
  if ((INIT_REMOTE)); then
    backup_run backup --bundle-root data/backup/bundle
    backup_run push --init-remote
    return 0
  fi
  backup_run scheduled
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
