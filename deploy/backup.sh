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
# TRADING_ENV_FILE are honoured from the environment.
#
# Backup env file (plan 24-36, D-29, WR-06): the BACKUP_ names live in their own file, read by the
# backup and ops compose services and by this script: TRADING_BACKUP_ENV_FILE, default the
# checkout's .env.backup (template: .env.backup.example). The shared TRADING_ENV_FILE / .env no
# longer carries them, so the always-on collector never holds a backup secret. For the soak project
# set TRADING_BACKUP_ENV_FILE to the soak env file (the trading-soak-backup unit and
# deploy/compose-soak.sh do).
#
# --install-soak-timer refuses a soak env file whose BACKUP_S3_BUCKET is empty or equals the one of
# the trading backup env file (TRADING_BACKUP_ENV_FILE, default the checkout's .env.backup): one
# bucket per project, never a shared snapshot series. Only variable names are printed, never a
# value.
#
# Local-only mode (261020-bkp): BACKUP_REMOTE=none in the backup env file the backup container
# reads (TRADING_BACKUP_ENV_FILE, default the checkout's .env.backup) is the operator's explicit
# opt-in to run without any off-host remote. The scheduled run and deploy/backup-drill.sh then
# make and verify the local bundle and restore-drill it, contact no remote, exit 0, print the
# multi-line warning "OFF-HOST COPY SKIPPED: this backup does not survive the loss of this host"
# and the marker line OFFSITE_COPY=skipped (a remote run prints OFFSITE_COPY=verified). --init-remote refuses in that
# mode (exit 2, nothing to initialise); --install-soak-timer accepts a soak env file without a
# bucket but still refuses the trading bucket. Unset, empty or s3 is the default: a missing
# BACKUP_S3_* variable still fails closed. Any other value refuses. A local-only backup never
# satisfies the soak pin (RUNBOOK 20.5).

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
  sed -n '3,44p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
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
  # a pattern replacement must not treat an ampersand in a path as the matched text (bash 5.2)
  shopt -u patsub_replacement 2>/dev/null || true
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

# Every path written into a unit file (the checkout for @TRADING_DIR@, the soak env file): no
# whitespace, no systemd specifier (%), no bash replacement (&), no quote; the character set of
# deploy/heartbeat.sh (UNIT_PATH_PATTERN) after the root or drive prefix (a drive-letter path is
# accepted for the Git Bash tests).
UNIT_PATH_RE='^(/|[A-Za-z]:/)[A-Za-z0-9._/+=,~-]+$'

require_root_and_plain_checkout() {
  if [[ -z ${TRADING_ROOT_PREFIX:-} && ${EUID} -ne 0 ]]; then
    die "$1 must run as root (sudo deploy/backup.sh $1)"
  fi
  [[ $REPO_ROOT != *[[:space:]]* ]] || die "checkout path contains whitespace: $REPO_ROOT"
  [[ $REPO_ROOT =~ $UNIT_PATH_RE ]] ||
    die "checkout path must hold only letters, digits and . _ / + = , ~ - (it is written into the units; no % or &): $REPO_ROOT"
}

install_timer() {
  require_root_and_plain_checkout --install-timer
  write_units trading-backup.timer "${UNITS[@]}"
}

# env_value FILE NAME: the value of NAME in an env file, read the way Compose reads it (plan
# 16-65): blank and comment lines skipped, an optional `export ` prefix, the LAST assignment wins,
# surrounding single or double quotes removed, an unquoted ` # comment` removed, a CR removed.
# Exit 0 prints the value (never logged), 1 when NAME is not assigned, 2 when the value cannot be
# determined without Compose (interpolation `$`, a backslash escape, an unterminated quote, text
# after a closing quote, a quote or `#` inside an unquoted value, or a bare `NAME` line without
# `=`, whose value Compose takes from the process environment): the caller fails closed.
env_value() {
  awk -v key="$2" '
    BEGIN { found = 0; bad = 0; out = ""; dq = "\""; sq = sprintf("%c", 39) }
    {
      line = $0
      sub(/\r$/, "", line)
      sub(/^[ \t]+/, "", line)
      if (line ~ /^export[ \t]+/) sub(/^export[ \t]+/, "", line)
      eq = index(line, "=")
      if (eq == 0) {
        bare = line
        sub(/[ \t]+#.*$/, "", bare)
        sub(/[ \t]+$/, "", bare)
        if (bare == key) bad = 1
        next
      }
      name = substr(line, 1, eq - 1)
      sub(/[ \t]+$/, "", name)
      if (name != key) next
      raw = substr(line, eq + 1)
      v = raw
      sub(/^[ \t]+/, "", v)
      q = substr(v, 1, 1)
      if (q == dq || q == sq) {
        rest = substr(v, 2)
        stop = index(rest, q)
        if (stop == 0) { bad = 1; next }
        val = substr(rest, 1, stop - 1)
        tail = substr(rest, stop + 1)
        if (tail !~ /^[ \t]*$/ && tail !~ /^[ \t]+#/) { bad = 1; next }
        if (q == dq && (index(val, "$") || index(val, "\\"))) { bad = 1; next }
      } else {
        val = raw
        if (match(val, /[ \t]#/)) val = substr(val, 1, RSTART - 1)
        sub(/^[ \t]+/, "", val)
        sub(/[ \t]+$/, "", val)
        if (index(val, "$") || index(val, "\\") || index(val, dq) || index(val, sq) || index(val, "#")) {
          bad = 1
          next
        }
      }
      found = 1
      out = val
    }
    END {
      if (bad) exit 2
      if (!found) exit 1
      print out
    }' "$1"
}

# bucket_of FILE LABEL: BACKUP_S3_BUCKET of FILE ("" when unassigned); dies when undeterminable.
bucket_of() {
  local value rc=0
  value="$(env_value "$1" BACKUP_S3_BUCKET)" || rc=$?
  if ((rc == 2)); then
    die "BACKUP_S3_BUCKET of the $2 env file cannot be determined the way Compose reads it (interpolation, escape or quoting): write it as a plain KEY=value line"
  elif ((rc != 0 && rc != 1)); then
    die "the $2 env file could not be read for BACKUP_S3_BUCKET"
  fi
  printf '%s' "$value"
}

# mode_of FILE LABEL: the backup mode of FILE, `s3` (BACKUP_REMOTE unset, empty or s3) or `none`
# (the explicit local-only opt-in); dies when undeterminable or another value (never printed).
mode_of() {
  local value rc=0
  value="$(env_value "$1" BACKUP_REMOTE)" || rc=$?
  if ((rc == 2)); then
    die "BACKUP_REMOTE of the $2 env file cannot be determined the way Compose reads it (interpolation, escape, quoting or a bare name): write it as a plain KEY=value line"
  elif ((rc != 0 && rc != 1)); then
    die "the $2 env file could not be read for BACKUP_REMOTE"
  fi
  case $value in
    '' | s3) printf 's3' ;;
    none) printf 'none' ;;
    *) die "BACKUP_REMOTE of the $2 env file must be empty, s3 or none (lower case)" ;;
  esac
}

# warn_offsite_skipped: the same warning the python side prints for a local-only run.
warn_offsite_skipped() {
  printf '%s\n' \
    '!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!' \
    'WARNING: OFF-HOST COPY SKIPPED: this backup does not survive the loss of this host.' \
    'WARNING: BACKUP_REMOTE=none (local-only mode) is set in the soak env file: every run of' \
    'WARNING: this timer keeps the bundle in data/backup on this host only (OFFSITE_COPY=skipped).' \
    'WARNING: a local-only backup never satisfies the soak pin (plan 16-43, RUNBOOK 20.5).' \
    '!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!' >&2
}

# check_init_remote_mode: --init-remote has nothing to initialise in local-only mode. The env
# file is the backup env file compose hands the backup container (plan 24-36); when it is missing,
# the python push fails closed on the missing BACKUP_ names.
check_init_remote_mode() {
  local env_file="${TRADING_BACKUP_ENV_FILE:-$REPO_ROOT/.env.backup}" mode
  [[ -r $env_file ]] || return 0
  mode="$(mode_of "$env_file" backup)"
  if [[ $mode == none ]]; then
    printf 'ERROR: %s\n' "BACKUP_REMOTE=none (local-only mode) in the env file: --init-remote has nothing to initialise (no remote is configured); run deploy/backup.sh without it" >&2
    exit 2
  fi
}

# check_soak_bucket: the soak env file names a bucket of its own (plan 16-55). The values are
# compared, never printed; a value that cannot be determined refuses the install (plan 16-65).
# In local-only mode (BACKUP_REMOTE=none, 261020-bkp) no bucket is needed, but a bucket that is
# set must still not be the trading bucket.
check_soak_bucket() {
  local trading_env="${TRADING_BACKUP_ENV_FILE:-$REPO_ROOT/.env.backup}" soak_bucket trading_bucket mode
  [[ -r $SOAK_ENV_FILE ]] || die "the soak env file is not readable: $SOAK_ENV_FILE"
  mode="$(mode_of "$SOAK_ENV_FILE" soak)"
  soak_bucket="$(bucket_of "$SOAK_ENV_FILE" soak)"
  if [[ $mode == none ]]; then
    warn_offsite_skipped
    [[ -n $soak_bucket ]] || return 0
  fi
  [[ -r $trading_env ]] || die "the trading env file is not readable: $trading_env (set TRADING_BACKUP_ENV_FILE to the env file trading-backup uses)"
  trading_bucket="$(bucket_of "$trading_env" trading)"
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
  # The path goes into a unit file: the rule of UNIT_PATH_RE.
  [[ $SOAK_ENV_FILE =~ $UNIT_PATH_RE ]] ||
    die "--soak-env-file must hold only letters, digits and . _ / + = , ~ - (no % or &): $SOAK_ENV_FILE"
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
  if ((INIT_REMOTE)); then
    check_init_remote_mode
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
