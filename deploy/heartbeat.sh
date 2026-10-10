#!/usr/bin/env bash
set -Eeuo pipefail
# External heartbeat sender for the collector (plan 16-50, D042 condition 1).
#
# Usage:
#   deploy/heartbeat.sh [--fail-ping] [--url-file PATH] [--dry-run]
#                                  one run: probe the collector, then ping the external monitor
#   deploy/heartbeat.sh -h | --help
#
# One run executes the collector probe (`python -m src.data.collector --healthcheck` inside the
# compose collector service, read-only) and sends exactly one success ping only while that probe
# passes. A failed probe sends no success ping, so the monitor goes quiet and alerts after its own
# period and grace. With --fail-ping (or HEARTBEAT_FAIL_PING=1) a failed probe sends one fail ping
# instead; that alerts at once and bypasses the grace period.
#
# Exit codes: 0 probe passed and ping delivered (or --dry-run), 1 probe failed, 2 usage,
#             3 probe passed but the ping was not delivered, 4 ping URL source missing or invalid.
#
# Secret rule: the ping URL is a secret. It is read only from a root-only file (the systemd
# credential `heartbeat-url`, else --url-file, else HEARTBEAT_URL_FILE, else the default path). It is
# never an argument, never exported, never logged, and the script refuses to run under xtrace.
# Fail-open: the only docker subcommand this script ever runs is `exec` of the read-only probe; a
# failed or undeliverable ping only changes the exit code.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

# Git Bash on Windows would otherwise rewrite container paths such as /app/.venv/bin/python.
export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PY=/app/.venv/bin/python
SERVICE=collector
DEFAULT_URL_FILE=/etc/trading/heartbeat.url
CREDENTIAL_NAME=heartbeat-url
# PLACEHOLDER (provenance label): a transport bound for the probe and for the ping, so a hung
# docker or curl cannot freeze the timer (a oneshot unit has no start timeout by default). Copied
# from the collector probe timeout in docker-compose.yml. It is not a monitor value (the interval
# and the grace are the operator's, decisions/16-DEC-O-12.md) and is never tuned.
DEFAULT_STEP_TIMEOUT_SECONDS=15
# Allow-list for the ping URL: https only; letters, digits, dot, underscore, tilde, colon, slash and
# hyphen. No userinfo, query, fragment, quote, backslash or whitespace can pass.
URL_PATTERN='^https://[A-Za-z0-9][A-Za-z0-9._~:/-]*$'

FAIL_PING=0
URL_FILE_FLAG=
STEP_TIMEOUT=
COMPOSE=()

usage() {
  sed -n '3,23p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
}

usage_error() {
  usage
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

# url_die MESSAGE: exit 4 with a fixed message. Never pass the URL or any part of it.
url_die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 4
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --fail-ping) FAIL_PING=1 ;;
      --url-file)
        (($# >= 2)) || usage_error "--url-file needs a path"
        URL_FILE_FLAG=$2
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
  if [[ ${HEARTBEAT_FAIL_PING:-0} != [01] ]]; then
    usage_error "HEARTBEAT_FAIL_PING must be 0 or 1"
  fi
  if [[ ${HEARTBEAT_FAIL_PING:-0} == 1 ]]; then
    FAIL_PING=1
  fi
  STEP_TIMEOUT="${HEARTBEAT_STEP_TIMEOUT_SECONDS:-$DEFAULT_STEP_TIMEOUT_SECONDS}"
  if [[ ! $STEP_TIMEOUT =~ ^[1-9][0-9]*$ ]]; then
    usage_error "HEARTBEAT_STEP_TIMEOUT_SECONDS must be a positive integer"
  fi
}

# resolve_url_source: sets URL_SOURCE (a file path) and URL_IS_CREDENTIAL (1 for the systemd
# credential, which systemd delivers as a private copy and whose mode is not ours to judge).
resolve_url_source() {
  URL_IS_CREDENTIAL=0
  if [[ -n ${CREDENTIALS_DIRECTORY:-} && -e ${CREDENTIALS_DIRECTORY}/$CREDENTIAL_NAME ]]; then
    URL_SOURCE="${CREDENTIALS_DIRECTORY}/$CREDENTIAL_NAME"
    URL_IS_CREDENTIAL=1
  elif [[ -n $URL_FILE_FLAG ]]; then
    URL_SOURCE="$(p "$URL_FILE_FLAG")"
  elif [[ -n ${HEARTBEAT_URL_FILE:-} ]]; then
    URL_SOURCE="$(p "$HEARTBEAT_URL_FILE")"
  else
    URL_SOURCE="$(p "$DEFAULT_URL_FILE")"
  fi
}

# validate_url_text TEXT: succeeds only for exactly one https URL of allowed characters.
validate_url_text() {
  LC_ALL=C
  [[ $1 =~ $URL_PATTERN ]]
}

# load_url: sets the non-exported shell variable PING_URL_VALUE from the resolved source, or exits 4.
load_url() {
  resolve_url_source
  [[ -f $URL_SOURCE && -r $URL_SOURCE ]] || url_die "ping URL source is missing or not a readable file: $URL_SOURCE"
  if ((!URL_IS_CREDENTIAL)) && posix_modes_supported; then
    local mode
    mode="$(stat -c '%a' -- "$URL_SOURCE" 2>/dev/null || true)"
    [[ $mode =~ ^[0-7]+$ ]] || url_die "cannot read the mode of the ping URL file: $URL_SOURCE"
    if ((8#$mode & 8#077)); then
      url_die "ping URL file is readable by group or others (run: chmod 600 on it): $URL_SOURCE"
    fi
  fi
  local content
  content="$(
    cat -- "$URL_SOURCE"
    printf x
  )" || url_die "ping URL source could not be read: $URL_SOURCE"
  content="${content%x}"
  content="${content%$'\n'}"
  validate_url_text "$content" || url_die "ping URL source does not hold exactly one https URL of allowed characters (content not shown)"
  PING_URL_VALUE=$content
}

# send_ping SUFFIX: one curl request. The URL reaches curl only through its standard-input
# configuration (printf is a builtin, so it is in no argv); curl's own stderr is discarded and only
# the exit status is reported. Returns curl's exit status.
send_ping() {
  local target="${PING_URL_VALUE%/}$1" rc=0
  printf 'url = "%s"\n' "$target" |
    curl --silent --fail --proto '=https' --proto-redir '=https' \
      --max-time "$STEP_TIMEOUT" --config - >/dev/null 2>&1 || rc=$?
  return "$rc"
}

# deliver LABEL SUFFIX: send the ping and report the outcome. Returns 0 when delivered.
deliver() {
  if ((DRY_RUN)); then
    printf '+ ping (%s): one https request through curl, URL not shown\n' "$1"
    return 0
  fi
  local rc=0
  send_ping "$2" || rc=$?
  if ((rc != 0)); then
    log "heartbeat: $1 ping not delivered (curl exit $rc)"
    return 1
  fi
  log "heartbeat: $1 ping delivered"
}

main() {
  if [[ $- == *x* ]]; then
    printf 'ERROR: refusing to run under xtrace: it would print the ping URL\n' >&2
    exit 2
  fi
  parse_args "$@"
  export DRY_RUN
  cd "$REPO_ROOT"
  load_url
  compose_init
  if ((!DRY_RUN)); then
    require_cmd timeout
    require_cmd curl
  fi

  local probe_ok=0
  if run timeout "$STEP_TIMEOUT" "${COMPOSE[@]}" exec -T "$SERVICE" "$PY" -m src.data.collector --healthcheck; then
    probe_ok=1
  fi

  if ((probe_ok)); then
    deliver success "" || return 3
    return 0
  fi
  if ((FAIL_PING)); then
    log "heartbeat: collector probe failed; sending a fail ping"
    deliver fail /fail || true
  else
    log "heartbeat: collector probe failed; no ping sent"
  fi
  return 1
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
