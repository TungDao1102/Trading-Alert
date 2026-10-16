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
#   deploy/backup.sh --install-soak-timer --soak-env-file PATH [--dry-run]
#                                              (root) install trading-soak-backup.service and
#                                              .timer for project trading-soak (plan 16-55); the
#                                              soak env file must name its own BACKUP_S3_BUCKET
#
# The wrapper holds no backup, encryption or remote logic: it only calls
# `python -m src.ops.backup <subcommand>` in the compose ops image and returns that command's exit
# code, so a failed backup fails the systemd oneshot service visibly. COMPOSE_PROJECT_NAME and
# TRADING_ENV_FILE are honoured from the environment. --install-soak-timer refuses a soak env file
# whose BACKUP_S3_BUCKET is empty or equals the one of the trading env file (TRADING_BACKUP_ENV_FILE,
# default the checkout's .env): one bucket per project, never a shared snapshot series. Only
# variable names are printed, never a value.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

# Git Bash on Windows would otherwise rewrite container paths such as /app/data/backup.
export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PY=/app/.venv/bin/python
UNIT_TOKEN='@TRADING_DIR@'
UNITS=(trading-backup.service trading-backup.timer)
SOAK_UNITS=(trading-soak-backup.service trading-soak-backup.timer)
SOAK_ENV_TOKEN='@SOAK_ENV_FILE@'

INIT_REMOTE=0
INSTALL_TIMER=0
INSTALL_SOAK_TIMER=0
SOAK_ENV_FILE=""
COMPOSE=()

usage() {
  sed -n '3,23p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
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
      --install-soak-timer) INSTALL_SOAK_TIMER=1 ;;
      --soak-env-file)
        (($# > 1)) || usage_error "--soak-env-file needs a path"
        SOAK_ENV_FILE=$2
        shift
        ;;
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
  if ((INSTALL_SOAK_TIMER && (INIT_REMOTE || INSTALL_TIMER))); then
    usage_error "--install-soak-timer cannot be combined with --init-remote or --install-timer"
  fi
  if ((INSTALL_SOAK_TIMER)) && [[ -z $SOAK_ENV_FILE ]]; then
    usage_error "--install-soak-timer needs --soak-env-file PATH"
  fi
  if ((!INSTALL_SOAK_TIMER)) && [[ -n $SOAK_ENV_FILE ]]; then
    usage_error "--soak-env-file belongs to --install-soak-timer"
  fi
}

# backup_run ARGS...: one python subcommand in the backup service (starts postgres as needed).
backup_run() {
  run "${COMPOSE[@]}" --profile ops run --rm -T backup "$PY" -m src.ops.backup "$@"
}

# write_units TIMER UNITS...: substitute the tokens into each template, write the changed ones,
# reload systemd when anything changed and enable the timer. SOAK_ENV_FILE fills its token.
write_units() {
  local timer=$1 unit_dir content changed=0 unit
  shift
  unit_dir="$(p /etc/systemd/system)"
  for unit in "$@"; do
    [[ -f $SCRIPT_DIR/systemd/$unit ]] || die "missing unit template: deploy/systemd/$unit"
    content="$(<"$SCRIPT_DIR/systemd/$unit")"
    content="${content//"$UNIT_TOKEN"/$REPO_ROOT}"
    content="${content//"$SOAK_ENV_TOKEN"/$SOAK_ENV_FILE}"
    write_if_changed "$unit_dir/$unit" "$content"
    if ((WROTE)); then
      changed=1
    fi
  done
  if ((changed)); then
    run systemctl daemon-reload
  fi
  run systemctl enable --now "$timer"
}

require_root_and_plain_checkout() {
  if [[ -z ${TRADING_ROOT_PREFIX:-} && ${EUID} -ne 0 ]]; then
    die "$1 must run as root (sudo deploy/backup.sh $1)"
  fi
  [[ $REPO_ROOT != *[[:space:]]* ]] || die "checkout path contains whitespace: $REPO_ROOT"
}

install_timer() {
  require_root_and_plain_checkout --install-timer
  write_units trading-backup.timer "${UNITS[@]}"
}

# env_value FILE NAME: the value of NAME in an env file (quotes and a CR removed). Never printed.
env_value() {
  awk -v key="$2" '
    index($0, key "=") == 1 {
      v = substr($0, length(key) + 2)
      sub(/\r$/, "", v)
      sub(/^"/, "", v)
      sub(/"$/, "", v)
      sub(/^\047/, "", v)
      sub(/\047$/, "", v)
      print v
      exit
    }' "$1"
}

# check_soak_bucket: the soak env file names a bucket of its own (plan 16-55). The values are
# compared, never printed.
check_soak_bucket() {
  local trading_env="${TRADING_BACKUP_ENV_FILE:-$REPO_ROOT/.env}" soak_bucket trading_bucket
  [[ -r $SOAK_ENV_FILE ]] || die "the soak env file is not readable: $SOAK_ENV_FILE"
  [[ -r $trading_env ]] || die "the trading env file is not readable: $trading_env (set TRADING_BACKUP_ENV_FILE to the env file trading-backup uses)"
  soak_bucket="$(env_value "$SOAK_ENV_FILE" BACKUP_S3_BUCKET)"
  trading_bucket="$(env_value "$trading_env" BACKUP_S3_BUCKET)"
  [[ -n $soak_bucket ]] || die "BACKUP_S3_BUCKET is empty in the soak env file: the soak project needs a bucket of its own"
  if [[ $soak_bucket == "$trading_bucket" ]]; then
    die "BACKUP_S3_BUCKET of the soak env file is the bucket of the trading env file: the soak project needs its own bucket (one snapshot series per bucket; RUNBOOK 20.5)"
  fi
}

install_soak_timer() {
  require_root_and_plain_checkout --install-soak-timer
  # Absolute: /... on the host (a drive-letter path is accepted for the Git Bash tests).
  [[ $SOAK_ENV_FILE == /* || $SOAK_ENV_FILE =~ ^[A-Za-z]:/ ]] ||
    die "--soak-env-file must be an absolute path: $SOAK_ENV_FILE"
  [[ $SOAK_ENV_FILE != *[[:space:]]* ]] || die "soak env file path contains whitespace"
  check_soak_bucket
  write_units trading-soak-backup.timer "${SOAK_UNITS[@]}"
}

main() {
  parse_args "$@"
  export DRY_RUN
  cd "$REPO_ROOT"
  if ((INSTALL_TIMER)); then
    install_timer
    return 0
  fi
  if ((INSTALL_SOAK_TIMER)); then
    install_soak_timer
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
