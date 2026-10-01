#!/usr/bin/env bash
set -Eeuo pipefail
# Provider-to-provider cutover: move the running collector, its Parquet store and its database
# from an OLD host to a NEW host with a bounded, reported data gap (D-14, D-15, D-20, D-21).
#
# Usage (run on the NEW host, or anywhere that can reach both over ssh):
#   deploy/migrate.sh [--dry-run] [--max-gap-minutes N] [--wait-seconds S]
#                     [--key-source PATH_OR_VOLUME] [--report-only]
#                     <old-ssh-target> <new-ssh-target|local>
#
# Fixed order: preflight; Parquet pre-sync while the old collector runs; stop the old
# collector; final sync; on the old host pg_dump + fingerprint + watermark snapshot; pull those
# artifacts; restore on the new host; start the new collector from its watermark; wait for its
# first new tick; print the cutover report and exit with the report's code
# (0 clean, 1 data loss, 2 input error, 3 OI gap above --max-gap-minutes).
#
# The script NEVER deletes data (rsync without any delete option, append-only
# --ignore-existing, temp files excluded) and NEVER stops anything on the old host except the
# collector service: no down, no power-off. A human shuts the old host down only after a clean
# report. --dry-run prints the ordered plan and executes nothing.
#
# Harness / non-default topologies (each defaults to the real-host form):
#   MIGRATE_OLD_COMPOSE      compose command prefix for the old side (default: ssh to the old
#                            host, then docker compose --project-directory ${MIGRATE_OLD_DIR}
#                            -p ${MIGRATE_OLD_PROJECT} --profile ops); split on whitespace
#   MIGRATE_NEW_COMPOSE      the same for the new side (local docker compose when <new> is local)
#   MIGRATE_RSYNC_SOURCE     rsync host spec (default: <old-ssh-target>)
#   MIGRATE_RSYNC_PATH       remote rsync command (default: docker run the ops image with the
#                            old named volumes mounted read-only; "sudo rsync" on the volume
#                            mount point is the documented fallback)
#   MIGRATE_REPORT_WINDOW_END  ISO UTC end of the gap window, passed to the report
#   MIGRATE_POLL_SECONDS     seconds between first-tick polls (default 15)
#
# The ssh key dir (--key-source: a host path or a named volume) must hold id_ed25519 and
# known_hosts; it is mounted read-only into the receiving container, never copied.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

# Git Bash on Windows would otherwise rewrite container paths such as /app/data/raw.
export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CUT=/app/data/backup/cutover
PY=/app/.venv/bin/python

MAX_GAP_MINUTES=60
WAIT_SECONDS=900
KEY_SOURCE="${MIGRATE_KEY_SOURCE:-${HOME:-/root}/.ssh/trading-migrate}"
REPORT_ONLY=0
OLD_TARGET=""
NEW_TARGET=""
OLD_STOPPED=0
FINISHED=0
OLD_COMPOSE=()
NEW_COMPOSE=()
RSYNC_SOURCE=""
RSYNC_PATH=""
RSYNC_SSH=""

usage() {
  sed -n '3,35p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
}

usage_error() {
  usage
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

parse_args() {
  local positional=()
  while (($# > 0)); do
    case "$1" in
      --max-gap-minutes | --wait-seconds | --key-source)
        (($# >= 2)) || usage_error "option $1 needs a value"
        case "$1" in
          --max-gap-minutes) MAX_GAP_MINUTES="$2" ;;
          --wait-seconds) WAIT_SECONDS="$2" ;;
          --key-source) KEY_SOURCE="$2" ;;
        esac
        shift 2
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      --report-only)
        REPORT_ONLY=1
        shift
        ;;
      -h | --help)
        usage
        exit 0
        ;;
      -*) usage_error "unknown option: $1" ;;
      *)
        positional+=("$1")
        shift
        ;;
    esac
  done
  ((${#positional[@]} == 2)) || usage_error "expected <old-ssh-target> <new-ssh-target|local>"
  OLD_TARGET="${positional[0]}"
  NEW_TARGET="${positional[1]}"
  [[ $MAX_GAP_MINUTES =~ ^[0-9]+$ ]] || usage_error "--max-gap-minutes must be a whole number"
  [[ $WAIT_SECONDS =~ ^[0-9]+$ ]] || usage_error "--wait-seconds must be a whole number"
  [[ -n $OLD_TARGET && -n $NEW_TARGET && -n $KEY_SOURCE ]] || usage_error "empty argument"
}

# Compose prefixes are bash arrays so no argument is ever re-split. An override string is split
# on whitespace once, here.
build_prefixes() {
  local ssh_ctl=(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes)
  local old_dir="${MIGRATE_OLD_DIR:-/opt/trading}" old_project="${MIGRATE_OLD_PROJECT:-trading}"
  local new_dir new_project="${MIGRATE_NEW_PROJECT:-trading}"

  if [[ -n ${MIGRATE_OLD_COMPOSE:-} ]]; then
    read -r -a OLD_COMPOSE <<<"$MIGRATE_OLD_COMPOSE"
  else
    OLD_COMPOSE=("${ssh_ctl[@]}" "$OLD_TARGET" docker compose --project-directory "$old_dir" -p "$old_project" --profile ops)
  fi

  if [[ -n ${MIGRATE_NEW_COMPOSE:-} ]]; then
    read -r -a NEW_COMPOSE <<<"$MIGRATE_NEW_COMPOSE"
  elif [[ $NEW_TARGET == local ]]; then
    new_dir="${MIGRATE_NEW_DIR:-$REPO_ROOT}"
    NEW_COMPOSE=(docker compose --project-directory "$new_dir" -p "$new_project" --profile ops)
  else
    new_dir="${MIGRATE_NEW_DIR:-/opt/trading}"
    NEW_COMPOSE=("${ssh_ctl[@]}" "$NEW_TARGET" docker compose --project-directory "$new_dir" -p "$new_project" --profile ops)
  fi

  RSYNC_SOURCE="${MIGRATE_RSYNC_SOURCE:-$OLD_TARGET}"
  RSYNC_PATH="${MIGRATE_RSYNC_PATH:-docker run --rm -i -v ${old_project}_rawdata:/data/raw:ro -v ${old_project}_backupdata:/data/backup:ro --entrypoint rsync trading-alert-ops:${IMAGE_TAG:-dev}}"
  RSYNC_SSH="ssh -i /keys/id_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/keys/known_hosts"
}

# old_ops / new_ops ARGS...: run a one-off command in the ops service of that side.
old_ops() { run "${OLD_COMPOSE[@]}" run --rm -T --no-deps ops "$@"; }
new_ops() { run "${NEW_COMPOSE[@]}" run --rm -T --no-deps ops "$@"; }

# probe CMD...: like run, but the exit status is the command's own; a dry run answers "no".
probe() {
  printf '+ %s\n' "$*"
  if [[ $DRY_RUN == 1 ]]; then
    return 1
  fi
  "$@"
}

# rsync_pull SRC DST: the ONLY data transfer. Append-only (--ignore-existing), no deletion
# option, atomic temp files excluded, strict host key checking against the mounted known_hosts.
# The receiver runs as root in the new ops container so it can read the 0600 key and keep the
# numeric owner (UID 10001) of the files it creates.
rsync_pull() {
  local src=$1 dst=$2
  run "${NEW_COMPOSE[@]}" run --rm -T --no-deps --user 0:0 -v "$KEY_SOURCE:/keys:ro" ops \
    rsync -a --numeric-ids --ignore-existing --exclude '.*.tmp' --stats \
    --rsync-path="$RSYNC_PATH" -e "$RSYNC_SSH" \
    "$RSYNC_SOURCE:$src" "$dst"
}

step() { printf '\n== step %s/10: %s\n' "$1" "$2"; }

preflight() {
  step 1 preflight
  if [[ $DRY_RUN != 1 ]]; then
    require_cmd docker
  fi
  if [[ $KEY_SOURCE == */* && $NEW_TARGET == local && $DRY_RUN != 1 ]]; then
    [[ -f $KEY_SOURCE/id_ed25519 && -f $KEY_SOURCE/known_hosts ]] ||
      die "--key-source $KEY_SOURCE must contain id_ed25519 and known_hosts"
  fi
  # Each side must answer and carry the Phase 13.1 ops image (the old host needs it too).
  old_ops test -f /app/src/ops/cutover.py || die "old side is not reachable or lacks the ops image"
  new_ops test -f /app/src/ops/cutover.py || die "new side is not reachable or lacks the ops image"
  # Stale cutover artifacts from an earlier attempt would be skipped by --ignore-existing and
  # silently reused: refuse instead of mixing runs.
  if probe "${OLD_COMPOSE[@]}" run --rm -T --no-deps ops test -e "$CUT/pg.dump"; then
    die "old side already has $CUT/pg.dump from an earlier run; inspect and remove it by hand first"
  fi
  if probe "${NEW_COMPOSE[@]}" run --rm -T --no-deps ops test -e "$CUT/pg.dump"; then
    die "new side already has $CUT/pg.dump from an earlier run; inspect and remove it by hand first"
  fi
}

presync() {
  step 2 "pre-sync Parquet while the old collector keeps running"
  rsync_pull /data/raw/ /app/data/raw/
}

stop_old_collector() {
  step 3 "stop the old collector (the only thing stopped on the old host)"
  run "${OLD_COMPOSE[@]}" stop collector
  OLD_STOPPED=1
}

final_sync() {
  step 4 "final Parquet sync with the old collector stopped"
  rsync_pull /data/raw/ /app/data/raw/
}

snapshot_old() {
  step 5 "pg_dump, fingerprint and watermark snapshot on the old host"
  old_ops "$PY" -m src.ops.backup dump --out "$CUT/pg.dump"
  old_ops "$PY" -m src.ops.cutover fingerprint --raw-root /app/data/raw --out "$CUT/old-fingerprint.json"
  old_ops "$PY" -m src.ops.cutover watermarks --out "$CUT/old-watermarks.json"
}

pull_artifacts() {
  step 6 "pull the dump, fingerprint and watermarks to the new host"
  rsync_pull "/data/backup/cutover/" "$CUT/"
}

# read_dump_hash: the sha256 recorded next to the dump by the old host, as read on the new host.
read_dump_hash() {
  local out hash
  if [[ $DRY_RUN == 1 ]]; then
    printf '+ %s run --rm -T --no-deps ops cat %s/pg.dump.sha256\n' "${NEW_COMPOSE[*]}" "$CUT" >&2
    printf '<sha256 from pg.dump.sha256>'
    return 0
  fi
  out="$("${NEW_COMPOSE[@]}" run --rm -T --no-deps ops cat "$CUT/pg.dump.sha256")" ||
    die "could not read $CUT/pg.dump.sha256 on the new side"
  read -r hash _ <<<"$out"
  [[ $hash =~ ^[0-9a-f]{64}$ ]] || die "$CUT/pg.dump.sha256 does not start with a sha256 digest"
  printf '%s' "$hash"
}

restore_new() {
  step 7 "restore the database on the new host (hash-verified, then alembic)"
  local hash
  run "${NEW_COMPOSE[@]}" up -d --wait --wait-timeout 180 postgres
  if [[ $DRY_RUN == 1 ]]; then
    printf '+ %s run --rm -T --no-deps ops cat %s/pg.dump.sha256
' "${NEW_COMPOSE[*]}" "$CUT"
    hash="<sha256 from pg.dump.sha256>"
  else
    hash="$(read_dump_hash)"
  fi
  new_ops "$PY" -m src.ops.backup restore-db --pg-dump "$CUT/pg.dump" --expect-sha256 "$hash"
}

start_new_collector() {
  step 8 "start the new collector (it resumes from the restored watermark)"
  run "${NEW_COMPOSE[@]}" up -d collector
}

# wait_first_tick: poll until every old OI watermark advanced. A timeout is not fatal: the
# report that follows then shows the trailing gap and decides the exit code.
wait_first_tick() {
  step 9 "wait for the first new tick (up to ${WAIT_SECONDS}s)"
  if [[ $DRY_RUN == 1 ]]; then
    printf '+ poll: cutover watermarks, then cutover advanced, every %ss until %ss elapsed\n' \
      "${MIGRATE_POLL_SECONDS:-15}" "$WAIT_SECONDS"
    return 0
  fi
  local deadline=$((SECONDS + WAIT_SECONDS)) rc
  while :; do
    new_ops "$PY" -m src.ops.cutover watermarks --out "$CUT/new-watermarks.json"
    rc=0
    new_ops "$PY" -m src.ops.cutover advanced \
      --old-watermarks "$CUT/old-watermarks.json" --new-watermarks "$CUT/new-watermarks.json" || rc=$?
    if ((rc == 0)); then
      log "first new tick observed"
      return 0
    fi
    ((rc == 1)) || die "tick probe failed with exit $rc"
    if ((SECONDS >= deadline)); then
      warn "no new tick within ${WAIT_SECONDS}s; the report shows the trailing gap"
      return 0
    fi
    sleep "${MIGRATE_POLL_SECONDS:-15}"
  done
}

# report: sets REPORT_RC to the verifier's exit code (0, 1, 2 or 3).
REPORT_RC=0
report() {
  step 10 "cutover report"
  local args=(
    "$PY" -m src.ops.cutover report
    --old-fingerprint "$CUT/old-fingerprint.json" --new-fingerprint "$CUT/new-fingerprint.json"
    --old-watermarks "$CUT/old-watermarks.json" --new-watermarks "$CUT/new-watermarks.json"
    --raw-root /app/data/raw --max-gap-minutes "$MAX_GAP_MINUTES" --json-out "$CUT/report.json"
  )
  if [[ -n ${MIGRATE_REPORT_WINDOW_END:-} ]]; then
    args+=(--window-end "$MIGRATE_REPORT_WINDOW_END")
  fi
  new_ops "$PY" -m src.ops.cutover fingerprint --raw-root /app/data/raw --out "$CUT/new-fingerprint.json"
  new_ops "$PY" -m src.ops.cutover watermarks --out "$CUT/new-watermarks.json"
  REPORT_RC=0
  new_ops "${args[@]}" || REPORT_RC=$?
}

print_notice() {
  cat <<EOF

The OLD host has NOT been shut down and nothing on it was removed; its collector is stopped.
Shut the old host down by hand only after the report above is clean (exit 0). Exit code
$REPORT_RC: 0 clean, 1 data loss, 2 input error, 3 OI gap above ${MAX_GAP_MINUTES} minutes.
EOF
}

# On a failure after the old collector was stopped, say how to resume collecting there.
on_exit() {
  local rc=$?
  if ((rc != 0 && OLD_STOPPED == 1 && FINISHED == 0)) && [[ $DRY_RUN != 1 ]]; then
    {
      printf '\nThe old collector is STOPPED and the migration did not finish (exit %s).\n' "$rc"
      printf 'To resume collecting on the old host, run: %s start collector\n' "${OLD_COMPOSE[*]}"
    } >&2
  fi
}

main() {
  parse_args "$@"
  export DRY_RUN
  build_prefixes
  trap on_exit EXIT
  if ((REPORT_ONLY)); then
    report
    FINISHED=1
    print_notice
    exit "$REPORT_RC"
  fi
  preflight
  presync
  stop_old_collector
  final_sync
  snapshot_old
  pull_artifacts
  restore_new
  start_new_collector
  wait_first_tick
  report
  FINISHED=1
  print_notice
  exit "$REPORT_RC"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
