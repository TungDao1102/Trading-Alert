#!/usr/bin/env bash
set -Eeuo pipefail
# Host freeze tick with an S3 witness (quick task 261114-12e, owner decision 16-DEC-HOST-TICK,
# which amends 16-DEC-O-01 with a least-privilege host credential; RUNBOOK 20.10).
#
# Usage:
#   deploy/freeze-witness.sh [--dry-run]
#                                  one tick (the ExecStart of trading-soak-freeze-witness.service):
#                                  run the freeze check of the pinned epoch in the image of the
#                                  running paper container and upload the exact line it appended,
#                                  create-only, to the S3 witness prefix
#   deploy/freeze-witness.sh --set-credential [--dry-run]
#                                  (root) store the witness credential, five key=value lines read
#                                  from standard input without echo, in the root-only file
#                                  /etc/trading/freeze-witness.conf (mode 0600)
#   deploy/freeze-witness.sh --install-timer --soak-env-file PATH [--dry-run]
#                                  (root) install trading-soak-freeze-witness.service and .timer
#                                  and enable the timer; the timer fires at the minute of the single
#                                  hourly cron of .github/workflows/paper_freeze_check.yml, read at
#                                  install time; PATH is the soak env file handed to
#                                  deploy/compose-soak.sh
#   deploy/freeze-witness.sh -h | --help
#
# One tick, in order: take the container of the paper service (deploy/compose-soak.sh ps) and its
# image, copy the pinned epoch out of the container with docker cp (the runtime's own pin is never
# opened), and run `python -m src.paper.freeze --check --from-allowlist` in that image on the copy:
# `docker run --rm --network none --read-only` with only a scratch directory mounted and only the
# names PAPER_TICK_SOURCE, PAPER_TICK_ID and PAPER_EVENT_SCHEDULE in its environment. The line the
# CLI appended must carry the host source, this tick id and the schedule; it is uploaded once,
# byte for byte, with the create-only header `If-None-Match: *` and its SHA-256 signed, as
# <witness prefix>/<epoch_id>/<YYYYMMDDTHHMMZ>-<32 hex>.jsonl. The slot in the key is a label: the
# lateness of a tick is decided only by the S3 server time of the object (16-DEC-HOST-TICK).
# There is no retry and no catch-up on purpose: a refused or late upload is a tick that does not
# count, and it is never re-sent.
#
# Credential: five lines, each key once and no other line: bucket_url, region, witness_prefix,
# access_key_id, secret_access_key. A tick reads them only from the systemd credential
# `freeze-witness` ($CREDENTIALS_DIRECTORY), never from a file path of its own.
#
# Exit codes:
#   0  uploaded, clean or SKIPPED; or a dry run
#   1  the tick could not run: no paper container, no pin, no line
#   2  usage, an invalid FREEZE_WITNESS_SCHEDULE, or xtrace
#   3  uploaded REGISTRY_DIFF
#   4  the credential is missing or invalid
#   5  the line does not carry the host identity (an image older than plan A of 261114-12e)
#   6  the upload was refused or failed
#
# Secret rule: the credential and the bucket URL are never an argument, never exported, never
# logged, never passed to a container; they reach curl only in curl's configuration on standard
# input (printf is a builtin, so it is in no argv). The script refuses to run under xtrace.
# Fail-open: the only docker subcommands are ps (through compose-soak.sh), inspect, cp from the
# container and one run --rm; it never stops, restarts, execs into or writes the paper runtime, and
# a failed tick only fails the oneshot unit.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

# Git Bash on Windows would otherwise rewrite container paths such as /app/.venv/bin/python.
export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PY=/app/.venv/bin/python
CREDENTIAL_NAME=freeze-witness
CREDENTIAL_FILE=/etc/trading/freeze-witness.conf
UNITS=(trading-soak-freeze-witness.service trading-soak-freeze-witness.timer)
TIMER_UNIT=trading-soak-freeze-witness.timer
WORKFLOW_FILE=.github/workflows/paper_freeze_check.yml
# PLACEHOLDER (provenance label): a transport bound for each docker and curl step, so a hung one
# cannot hang the oneshot. It is never an evidence value: the grace of 1800 s of
# freeze_tick_grace_seconds is the only lateness rule.
DEFAULT_STEP_TIMEOUT_SECONDS=120
# STRUCTURAL: the line is one short JSON object; more than this is not a freeze line.
MAX_LINE_BYTES=4096

# Allow-lists for the credential values. No quote, backslash or whitespace can pass, so every value
# is safe inside curl's configuration string.
BUCKET_URL_PATTERN='^https://[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?(/[A-Za-z0-9][A-Za-z0-9._-]*)?$'
REGION_PATTERN='^[a-z0-9-]{2,32}$'
PREFIX_PATTERN='^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$'
KEY_ID_PATTERN='^[A-Za-z0-9]{16,128}$'
SECRET_PATTERN='^[A-Za-z0-9/+=]{16,128}$'
UNIT_PATH_PATTERN='^/[A-Za-z0-9._/+=,~-]+$'
SCRATCH_PATTERN='^[A-Za-z0-9._/+=~:@-]+$'
SCHEDULE_PATTERN='^([0-9]|[1-5][0-9]) \* \* \* \*$'
EPOCH_PATTERN='"epoch_id": *"([A-Za-z0-9._-]{1,128})"'
CRON_LINE_PATTERN="^[[:space:]]*-?[[:space:]]*cron:[[:space:]]*[\"']([^\"']+)[\"'][[:space:]]*(#.*)?\$"

TOKEN_DIR='@TRADING_DIR@'
TOKEN_CREDENTIAL='@CREDENTIAL_FILE@'
TOKEN_SOAK_ENV='@SOAK_ENV_FILE@'
TOKEN_MINUTE='@CRON_MINUTE@'
TOKEN_SCHEDULE='@SCHEDULE@'

SET_CREDENTIAL=0
INSTALL_TIMER=0
SOAK_ENV_FILE=
STEP_TIMEOUT=
SCRATCH=
SLOT=
TICK_ID=
CID=
OUTCOME=
SCHEDULE=
# The credential values: non-exported shell variables, never printed.
CRED_BUCKET_URL=
CRED_REGION=
CRED_PREFIX=
CRED_KEY_ID=
CRED_SECRET=

usage() {
  awk 'NR >= 3 && /^#/ { print; next } NR >= 3 { exit }' "${BASH_SOURCE[0]}" |
    sed 's/^# \{0,1\}//' >&2
}

usage_error() {
  usage
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

# fail CODE MESSAGE: print a fixed message and exit with CODE. Never pass a credential value.
fail() {
  printf 'ERROR: %s\n' "$2" >&2
  exit "$1"
}

# cred_die MESSAGE: exit 4 with a fixed message. Never pass the credential or any part of it.
cred_die() {
  fail 4 "$1"
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --set-credential) SET_CREDENTIAL=1 ;;
      --install-timer) INSTALL_TIMER=1 ;;
      --soak-env-file)
        (($# >= 2)) || usage_error "--soak-env-file needs a path"
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
  if ((SET_CREDENTIAL && INSTALL_TIMER)); then
    usage_error "--set-credential and --install-timer cannot be combined"
  fi
  if ((INSTALL_TIMER)); then
    [[ -n $SOAK_ENV_FILE ]] || usage_error "--install-timer needs --soak-env-file PATH (the soak env file of deploy/compose-soak.sh)"
    [[ $SOAK_ENV_FILE =~ $UNIT_PATH_PATTERN ]] || usage_error "--soak-env-file must be absolute and hold only letters, digits and . _ / + = , ~ -"
  elif [[ -n $SOAK_ENV_FILE ]]; then
    usage_error "--soak-env-file is only valid with --install-timer"
  fi
  STEP_TIMEOUT="${FREEZE_WITNESS_STEP_TIMEOUT_SECONDS:-$DEFAULT_STEP_TIMEOUT_SECONDS}"
  if [[ ! $STEP_TIMEOUT =~ ^[1-9][0-9]*$ ]]; then
    usage_error "FREEZE_WITNESS_STEP_TIMEOUT_SECONDS must be a positive integer"
  fi
}

# prefix_has_dot_segment VALUE: succeeds when a path segment is . or ..
prefix_has_dot_segment() {
  local IFS=/ segment
  local -a segments=()
  read -ra segments <<<"$1"
  for segment in "${segments[@]}"; do
    if [[ $segment == . || $segment == .. ]]; then
      return 0
    fi
  done
  return 1
}

# parse_credential_text TEXT: sets the five CRED_ variables from exactly five key=value lines, or
# exits 4 with a fixed message. Nothing of TEXT is ever printed.
parse_credential_text() {
  LC_ALL=C
  local text=$1 line key value seen=' ' count=0
  local -a lines=()
  [[ -n $text ]] || cred_die "the witness credential is empty"
  mapfile -t lines <<<"$text"
  for line in "${lines[@]}"; do
    count=$((count + 1))
    [[ $line =~ ^([a-z_]+)=(.*)$ ]] || cred_die "the witness credential holds a line that is not key=value (content not shown)"
    key=${BASH_REMATCH[1]}
    value=${BASH_REMATCH[2]}
    [[ $seen != *" $key "* ]] || cred_die "the witness credential names a key twice (content not shown)"
    seen+="$key "
    case $key in
      bucket_url)
        [[ $value =~ $BUCKET_URL_PATTERN ]] || cred_die "the witness credential bucket_url is not an https bucket URL of allowed characters (value not shown)"
        CRED_BUCKET_URL=$value
        ;;
      region)
        [[ $value =~ $REGION_PATTERN ]] || cred_die "the witness credential region is not valid (value not shown)"
        CRED_REGION=$value
        ;;
      witness_prefix)
        [[ $value =~ $PREFIX_PATTERN ]] || cred_die "the witness credential witness_prefix is not valid (value not shown)"
        if prefix_has_dot_segment "$value"; then
          cred_die "the witness credential witness_prefix has a . or .. segment (value not shown)"
        fi
        CRED_PREFIX=$value
        ;;
      access_key_id)
        [[ $value =~ $KEY_ID_PATTERN ]] || cred_die "the witness credential access_key_id is not valid (value not shown)"
        CRED_KEY_ID=$value
        ;;
      secret_access_key)
        [[ $value =~ $SECRET_PATTERN ]] || cred_die "the witness credential secret_access_key is not valid (value not shown)"
        CRED_SECRET=$value
        ;;
      *) cred_die "the witness credential names a key that is not one of the five (content not shown)" ;;
    esac
  done
  ((count == 5)) || cred_die "the witness credential must hold exactly five key=value lines (content not shown)"
}

# load_credential: the credential only from the systemd credential, never from a path of our own.
load_credential() {
  local source_file="${CREDENTIALS_DIRECTORY:-}/$CREDENTIAL_NAME" content
  if [[ -z ${CREDENTIALS_DIRECTORY:-} || ! -f $source_file || ! -r $source_file ]]; then
    cred_die "the systemd credential $CREDENTIAL_NAME is missing; a tick runs only under trading-soak-freeze-witness.service (LoadCredential)"
  fi
  content="$(
    cat -- "$source_file"
    printf x
  )" || cred_die "the systemd credential $CREDENTIAL_NAME could not be read"
  content="${content%x}"
  content="${content%$'\n'}"
  parse_credential_text "$content"
}

require_schedule() {
  if [[ -z ${FREEZE_WITNESS_SCHEDULE:-} || ! ${FREEZE_WITNESS_SCHEDULE} =~ $SCHEDULE_PATTERN ]]; then
    fail 2 "FREEZE_WITNESS_SCHEDULE must be one hourly cron of the form 'M * * * *' (the workflow cron)"
  fi
}

# compute_slot: SLOT is the label of the latest slot minute at or before now (a key label only).
compute_slot() {
  local now minute slot_epoch
  now="$(date -u +%s)"
  [[ $now =~ ^[0-9]+$ ]] || fail 1 "cannot read the host clock"
  minute=${FREEZE_WITNESS_SCHEDULE%% *}
  slot_epoch=$((now - ((now - minute * 60) % 3600)))
  SLOT="$(date -u -d "@$slot_epoch" +%Y%m%dT%H%MZ)"
  [[ $SLOT =~ ^[0-9]{8}T[0-9]{4}Z$ ]] || fail 1 "cannot compute the slot label"
}

cleanup() {
  if [[ -n $SCRATCH && -d $SCRATCH ]]; then
    rm -rf -- "$SCRATCH" || true
  fi
}

# dry_run_tick: print the planned steps; run no docker and no curl.
dry_run_tick() {
  compute_slot
  run bash "$SCRIPT_DIR/compose-soak.sh" ps -q paper
  run docker inspect --format '{{.Image}}' '<paper container>'
  run docker cp '<paper container>:/app/logs/paper/pinned_epoch.json' '<scratch>/pinned_epoch.json'
  run docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
    --mount 'type=bind,src=<scratch>,dst=/scratch' \
    -e PAPER_TICK_SOURCE=host -e 'PAPER_TICK_ID=<tick id>' -e "PAPER_EVENT_SCHEDULE=$FREEZE_WITNESS_SCHEDULE" \
    '<paper image>' "$PY" -m src.paper.freeze --check --from-allowlist \
    --pinned-state /scratch/pinned_epoch.json --diff-log /scratch/registry_diff.jsonl \
    --registry-root /app/params
  printf '+ upload (create-only, If-None-Match: *): %s/%s-%s.jsonl; URL and credential not shown\n' \
    '<epoch_id>' "$SLOT" '<tick id>'
}

# one_line_check LINE_FILE: exit 5 unless the file is one short line that carries the host identity
# of this tick; sets OUTCOME.
one_line_check() {
  local file=$1 size newlines last outcome
  size="$(wc -c <"$file")"
  size=${size//[[:space:]]/}
  newlines="$(tr -cd '\n' <"$file" | wc -c)"
  newlines=${newlines//[[:space:]]/}
  last="$(tail -c 1 "$file" | od -An -tx1)"
  last=${last//[[:space:]]/}
  if ((size < 2 || size > MAX_LINE_BYTES)) || ((newlines != 1)) || [[ $last != 0a ]]; then
    fail 5 "the freeze line is not exactly one newline-terminated line of at most $MAX_LINE_BYTES bytes; nothing uploaded"
  fi
  if ! grep -qF -- '"source":"host"' "$file" ||
    ! grep -qF -- "\"tick_id\":\"$TICK_ID\"" "$file" ||
    ! grep -qF -- "\"schedule\":\"$FREEZE_WITNESS_SCHEDULE\"" "$file"; then
    fail 5 "the line does not carry the host source, this tick id and the schedule: the image predates the host tick source (plan A of 261114-12e) or the line is not a host line; nothing uploaded"
  fi
  OUTCOME=
  for outcome in clean REGISTRY_DIFF SKIPPED; do
    if grep -qF -- "\"outcome\":\"$outcome\"" "$file"; then
      OUTCOME=$outcome
    fi
  done
  [[ -n $OUTCOME ]] || fail 5 "the line has no known outcome; nothing uploaded"
}

# upload_line LINE_FILE KEY SHA: one create-only PUT, no retry. The credential and the bucket URL
# reach curl only through its standard-input configuration.
upload_line() {
  local file=$1 key=$2 sha=$3 rc=0 code=''
  code="$(
    printf 'url = "%s/%s"\nuser = "%s:%s"\n' "$CRED_BUCKET_URL" "$key" "$CRED_KEY_ID" "$CRED_SECRET" |
      curl --silent --fail --proto '=https' --proto-redir '=https' --max-time "$STEP_TIMEOUT" \
        --aws-sigv4 "aws:amz:$CRED_REGION:s3" --upload-file "$file" \
        -H 'If-None-Match: *' -H "x-amz-content-sha256: $sha" \
        --output /dev/null --write-out '%{http_code}' --config - 2>/dev/null
  )" || rc=$?
  if ((rc != 0)); then
    [[ $code =~ ^[0-9]{3}$ ]] || code=000
    log "witness: upload not accepted (curl exit $rc, HTTP $code); this host tick does not count and is never re-sent"
    if [[ $code == 412 ]]; then
      log "witness: an object already exists at this key; nothing was replaced"
    fi
    exit 6
  fi
}

# run_tick: one host freeze tick.
run_tick() {
  load_credential
  require_schedule
  if ((DRY_RUN)); then
    dry_run_tick
    return 0
  fi
  require_cmd docker
  require_cmd timeout
  require_cmd curl
  require_cmd sha256sum
  require_cmd od
  compute_slot
  local tick_id id_lines cid_out image base epoch_id cli_rc=0 line_file sha key
  tick_id="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
  [[ $tick_id =~ ^[0-9a-f]{32}$ ]] || fail 1 "cannot draw a tick id"
  TICK_ID=$tick_id

  cid_out="$(timeout "$STEP_TIMEOUT" bash "$SCRIPT_DIR/compose-soak.sh" ps -q paper)" || fail 1 "cannot list the paper container of the soak project"
  id_lines="$(grep -E '^[0-9a-f]{12,64}$' <<<"$cid_out" || true)"
  [[ $id_lines =~ ^[0-9a-f]{12,64}$ ]] || fail 1 "no single running paper container found in the soak project"
  CID=$id_lines
  image="$(timeout "$STEP_TIMEOUT" docker inspect --format '{{.Image}}' "$CID")" || fail 1 "cannot inspect the paper container"
  [[ $image =~ ^sha256:[0-9a-f]{64}$ ]] || fail 1 "the paper container image id is not a sha256 id"

  base="${RUNTIME_DIRECTORY:-${TMPDIR:-/tmp}}"
  SCRATCH="$(mktemp -d "$base/freeze-witness.XXXXXX")" || fail 1 "cannot create a scratch directory under $base"
  trap cleanup EXIT
  [[ $SCRATCH =~ $SCRATCH_PATTERN ]] || fail 1 "the scratch directory path holds a character that is not allowed"

  timeout "$STEP_TIMEOUT" docker cp "$CID:/app/logs/paper/pinned_epoch.json" "$SCRATCH/pinned_epoch.json" >/dev/null ||
    fail 1 "cannot copy the pinned epoch out of the paper container"
  local pin
  pin="$(<"$SCRATCH/pinned_epoch.json")"
  [[ $pin =~ $EPOCH_PATTERN ]] || fail 1 "the pinned epoch file holds no epoch_id"
  epoch_id=${BASH_REMATCH[1]}

  timeout "$STEP_TIMEOUT" docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=$SCRATCH,dst=/scratch" \
    -e PAPER_TICK_SOURCE=host -e "PAPER_TICK_ID=$TICK_ID" -e "PAPER_EVENT_SCHEDULE=$FREEZE_WITNESS_SCHEDULE" \
    "$image" "$PY" -m src.paper.freeze --check --from-allowlist \
    --pinned-state /scratch/pinned_epoch.json --diff-log /scratch/registry_diff.jsonl \
    --registry-root /app/params >&2 || cli_rc=$?
  if ((cli_rc != 0 && cli_rc != 3)); then
    fail 1 "the freeze check exited $cli_rc; nothing uploaded"
  fi
  line_file="$SCRATCH/registry_diff.jsonl"
  [[ -f $line_file ]] || fail 1 "the freeze check wrote no line"
  one_line_check "$line_file"

  sha="$(sha256sum -- "$line_file")"
  sha=${sha%% *}
  [[ $sha =~ ^[0-9a-f]{64}$ ]] || fail 1 "cannot hash the line"
  key="$CRED_PREFIX/$epoch_id/$SLOT-$TICK_ID.jsonl"
  upload_line "$line_file" "$key" "$sha"
  log "witness: created $epoch_id/$SLOT-$TICK_ID.jsonl ($OUTCOME)"
  if [[ $OUTCOME == REGISTRY_DIFF ]]; then
    return 3
  fi
  return 0
}

require_root() {
  if [[ -z ${TRADING_ROOT_PREFIX:-} && ${EUID} -ne 0 ]]; then
    die "$1 must run as root (sudo deploy/freeze-witness.sh $1 ...)"
  fi
}

# set_credential: read exactly five lines from standard input without echo and store them, mode
# 0600. The values are never printed; they are passed to write_if_changed as a shell argument,
# never to a command.
set_credential() {
  require_root --set-credential
  local line content='' extra='' index path
  path="$(p "$CREDENTIAL_FILE")"
  if [[ -t 0 ]]; then
    printf 'Paste the five credential lines (input is hidden):\n' >&2
  fi
  for index in 1 2 3 4 5; do
    line=''
    IFS= read -rs line || [[ -n $line ]] || cred_die "no credential was provided on standard input (five key=value lines are needed)"
    if ((index > 1)); then
      content+=$'\n'
    fi
    content+=$line
  done
  if [[ ! -t 0 ]] && { IFS= read -rs extra || [[ -n $extra ]]; }; then
    cred_die "more than five lines were provided on standard input (content not shown)"
  fi
  parse_credential_text "$content"
  write_if_changed "$path" "$content" 0600
  if ((DRY_RUN)); then
    log "freeze-witness: would store the credential in $path (values not shown)"
    return 0
  fi
  chmod 0600 -- "$path"
  if ((WROTE)); then
    log "freeze-witness: credential stored in $path (values not shown)"
  else
    log "freeze-witness: credential in $path unchanged (values not shown)"
  fi
}

# read_workflow_cron: sets SCHEDULE to the one hourly cron of the freeze workflow, or dies.
read_workflow_cron() {
  local workflow="$REPO_ROOT/$WORKFLOW_FILE" line cron=''
  local -a crons=()
  [[ -f $workflow ]] || die "missing workflow file: $WORKFLOW_FILE"
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line%$'\r'}
    if [[ $line =~ $CRON_LINE_PATTERN ]]; then
      if [[ ${#crons[@]} -eq 0 || ${crons[0]} != "${BASH_REMATCH[1]}" ]]; then
        crons+=("${BASH_REMATCH[1]}")
      fi
    fi
  done <"$workflow"
  if ((${#crons[@]} != 1)); then
    die "$WORKFLOW_FILE must name exactly one schedule cron, found ${#crons[@]}"
  fi
  cron=${crons[0]}
  [[ $cron =~ $SCHEDULE_PATTERN ]] || die "the cron of $WORKFLOW_FILE is not of the hourly form 'M * * * *'"
  SCHEDULE=$cron
}

# install_timer: write the two units with the workflow minute and enable the timer.
install_timer() {
  require_root --install-timer
  [[ $REPO_ROOT != *[[:space:]]* ]] || die "checkout path contains whitespace: $REPO_ROOT"
  # a pattern replacement must not treat an ampersand in a path as the matched text
  shopt -u patsub_replacement 2>/dev/null || true
  local credential_path unit_dir content changed=0 unit minute
  credential_path="$(p "$CREDENTIAL_FILE")"
  if [[ ! -f $credential_path ]]; then
    if ((DRY_RUN)); then
      warn "no credential file at $CREDENTIAL_FILE yet; run 'sudo deploy/freeze-witness.sh --set-credential' before the real install"
    else
      cred_die "no credential file at $CREDENTIAL_FILE; run 'sudo deploy/freeze-witness.sh --set-credential' first"
    fi
  fi
  if [[ ! -f "$(p "$SOAK_ENV_FILE")" ]]; then
    if ((DRY_RUN)); then
      warn "no soak env file at $SOAK_ENV_FILE yet; create it from deploy/soak.env.example before the real install"
    else
      die "no soak env file at $SOAK_ENV_FILE; create it from deploy/soak.env.example first"
    fi
  fi
  read_workflow_cron
  minute="$(printf '%02d' "${SCHEDULE%% *}")"
  unit_dir="$(p /etc/systemd/system)"
  for unit in "${UNITS[@]}"; do
    [[ -f $SCRIPT_DIR/systemd/$unit ]] || die "missing unit template: deploy/systemd/$unit"
    content="$(<"$SCRIPT_DIR/systemd/$unit")"
    content="${content//"$TOKEN_DIR"/$REPO_ROOT}"
    content="${content//"$TOKEN_CREDENTIAL"/$CREDENTIAL_FILE}"
    content="${content//"$TOKEN_SOAK_ENV"/$SOAK_ENV_FILE}"
    content="${content//"$TOKEN_MINUTE"/$minute}"
    content="${content//"$TOKEN_SCHEDULE"/$SCHEDULE}"
    write_if_changed "$unit_dir/$unit" "$content"
    if ((WROTE)); then
      changed=1
    fi
  done
  if ((changed)); then
    run systemctl daemon-reload
  fi
  run systemctl enable --now "$TIMER_UNIT"
  if ((changed)); then
    run systemctl restart "$TIMER_UNIT"
  fi
}

main() {
  if [[ $- == *x* ]]; then
    printf 'ERROR: refusing to run under xtrace: it would print the witness credential\n' >&2
    exit 2
  fi
  parse_args "$@"
  export DRY_RUN
  cd "$REPO_ROOT"
  if ((SET_CREDENTIAL)); then
    set_credential
    return 0
  fi
  if ((INSTALL_TIMER)); then
    install_timer
    return 0
  fi
  run_tick
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
