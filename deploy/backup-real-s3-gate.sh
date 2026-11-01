#!/usr/bin/env bash
set -Eeuo pipefail
# D064 real-S3 gate (261020-bkp): run the detection claims of the Parquet push against the remote
# the backup is configured for (BACKUP_* names of the backup env file), under a throwaway prefix.
#
# Usage:
#   deploy/backup-real-s3-gate.sh                        print the plan (prefix, claims); no remote
#                                                        call, nothing written
#   deploy/backup-real-s3-gate.sh --execute [--evidence-dir DIR]
#                                                        run every claim and write the evidence file
#                                                        DIR/d064-real-s3-gate-<UTC>.txt
#   add --dry-run to either form to print the docker command only
#
# The wrapper holds no remote logic: it runs `python -m src.ops.backup real-s3-gate` in the compose
# ops image, which builds the remote with the same mapping as the backup, writes only below a new
# prefix d064-gate-<UTC>-<12 hex> directly under the configured bucket (refused unless empty),
# purges that prefix in every exit path and prints one PASS or FAIL line per claim. --execute
# copies that output into the evidence file (default DIR: $HOME/trading-evidence, outside the
# checkout) even when a claim fails. Exit codes: 0 every claim passed, 1 a claim failed or the run
# was interrupted, 2 a usage or configuration error (nothing was touched). COMPOSE_PROJECT_NAME and
# TRADING_ENV_FILE are honoured. The BACKUP_ names come from the backup env file (plan 24-36, D-29):
# TRADING_BACKUP_ENV_FILE, default the checkout's .env.backup, which compose hands to the ops
# service; point both TRADING_ENV_FILE and TRADING_BACKUP_ENV_FILE at the soak env file to gate the
# soak bucket. No value of the env file is printed; the bucket name appears as <bucket>.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

# Git Bash on Windows would otherwise rewrite container paths.
export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PY=/app/.venv/bin/python
EXECUTE=0
EVIDENCE_DIR="${HOME:-/tmp}/trading-evidence"
EVIDENCE_FILE=""
COMPOSE=()

usage() {
  sed -n '3,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
}

usage_error() {
  usage
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --execute) EXECUTE=1 ;;
      --evidence-dir)
        (($# > 1)) || usage_error "--evidence-dir needs a directory"
        EVIDENCE_DIR=$2
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
  [[ -n $EVIDENCE_DIR ]] || usage_error "--evidence-dir must not be empty"
}

# on_exit: say where the evidence is, whatever the outcome (the remote prefix is purged by python).
on_exit() {
  local rc=$?
  if [[ -n $EVIDENCE_FILE && -f $EVIDENCE_FILE ]]; then
    log "evidence: $EVIDENCE_FILE (exit $rc)"
  fi
}

main() {
  parse_args "$@"
  export DRY_RUN
  cd "$REPO_ROOT"
  compose_init
  local gate=("${COMPOSE[@]}" --profile ops run --rm -T --no-deps ops "$PY" -m src.ops.backup real-s3-gate)
  if ((!EXECUTE)); then
    run "${gate[@]}"
    return 0
  fi
  gate+=(--execute)
  if [[ ${DRY_RUN} == 1 ]]; then
    run "${gate[@]}"
    return 0
  fi
  mkdir -p "$EVIDENCE_DIR"
  EVIDENCE_FILE="$EVIDENCE_DIR/d064-real-s3-gate-$(date -u +%Y%m%dT%H%M%SZ).txt"
  [[ ! -e $EVIDENCE_FILE ]] || die "the evidence file already exists: $EVIDENCE_FILE"
  trap on_exit EXIT
  printf '+ %s > %s\n' "${gate[*]}" "$EVIDENCE_FILE"
  local rc=0
  "${gate[@]}" >"$EVIDENCE_FILE" || rc=$?
  cat "$EVIDENCE_FILE"
  return "$rc"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
