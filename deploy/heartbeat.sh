#!/usr/bin/env bash
set -Eeuo pipefail
# External heartbeat sender for the collector (plan 16-50, D042 condition 1), with
# --target paper for the paper runtime of the soak project (plan 16-56, 16-DEC-HUNG-RUNTIME)
# and with --target live for the live runtime (plan 24-24, D-30, R-8, inherited item 16-50).
#
# Usage:
#   deploy/heartbeat.sh [--fail-ping] [--url-file PATH] [--dry-run]
#                                  one run: probe the collector, then ping the external monitor
#   deploy/heartbeat.sh --set-url [--url-file PATH] [--dry-run]
#                                  (root) store the ping URL, read as one line from standard input
#                                  without echo, in the root-only URL file (mode 0600)
#   deploy/heartbeat.sh --install-timer --interval-seconds N [--fail-ping] [--url-file PATH]
#                       [--dry-run]
#                                  (root) install trading-heartbeat.service and
#                                  trading-heartbeat.timer and enable the timer; N is the
#                                  operator's ping interval in seconds and has no default
#   deploy/heartbeat.sh --target paper [--fail-ping] [--url-file PATH] [--dry-run]
#                                  one run of the separate PAPER heartbeat (plan 16-56,
#                                  16-DEC-HUNG-RUNTIME): probe the paper runtime's liveness
#                                  (`python -m src.paper.runtime --liveness` inside the paper
#                                  service of the soak project, through deploy/compose-soak.sh),
#                                  then ping the paper check of the external monitor
#   deploy/heartbeat.sh --target paper --set-url [--url-file PATH] [--dry-run]
#   deploy/heartbeat.sh --target paper --install-timer --interval-seconds N
#                       --soak-env-file PATH [--fail-ping] [--url-file PATH] [--dry-run]
#                                  (root) the same for the paper check: its own URL file
#                                  (/etc/trading/heartbeat-paper.url by default, or
#                                  HEARTBEAT_PAPER_URL_FILE), its own systemd credential
#                                  `heartbeat-paper-url`, its own units
#                                  trading-soak-paper-heartbeat.service and .timer; PATH is the
#                                  soak env file the unit hands to deploy/compose-soak.sh
#   deploy/heartbeat.sh --target live [--fail-ping] [--url-file PATH] [--dry-run]
#                                  one run of the separate LIVE heartbeat (plan 24-24): probe the
#                                  live runtime's liveness (`python -m src.live.runtime
#                                  --liveness` inside the live service, read-only
#                                  `docker compose exec -T`), then ping the live check of the
#                                  external monitor
#   deploy/heartbeat.sh --target live --set-url [--url-file PATH] [--dry-run]
#   deploy/heartbeat.sh --target live --install-timer --interval-seconds N [--fail-ping]
#                       [--url-file PATH] [--dry-run]
#                                  (root) the same for the live check: its own URL file
#                                  (/etc/trading/heartbeat-live.url by default, or
#                                  HEARTBEAT_LIVE_URL_FILE), its own systemd credential
#                                  `heartbeat-live-url`, its own units
#                                  trading-live-heartbeat.service and .timer
#   deploy/heartbeat.sh -h | --help
#
# --target collector (the default) is everything above the paper lines, unchanged. The paper
# target never reads the collector's URL file or credential, refuses --url-file naming the
# collector's default file, and its probe passes only while the paper runtime has no held marker
# and both its event-loop stamp and its last market message are younger than the configured feed
# silence timeout (never the bar-age healthcheck). The live target likewise has its own URL file,
# credential and units, refuses --url-file naming the collector's or the paper's default file,
# and its probe passes only while the live runtime has no held marker and a fresh liveness stamp.
# The check period (recommended 60 s) and grace (recommended 120 s) are set by the owner in the
# monitor; --install-timer --interval-seconds N has no default for any target.
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
# Allow-list for a URL file path that is baked into a unit (no whitespace and no systemd
# specifier characters such as the percent sign).
UNIT_PATH_PATTERN='^/[A-Za-z0-9._/+=,~-]+$'

# The default URL files of the other checks: no target may use another target's file.
PAPER_URL_FILE=/etc/trading/heartbeat-paper.url
LIVE_URL_FILE=/etc/trading/heartbeat-live.url

TOKEN_DIR='@TRADING_DIR@'
TOKEN_URL_FILE='@URL_FILE@'
TOKEN_FAIL_PING='@FAIL_PING@'
TOKEN_INTERVAL='@INTERVAL_SECONDS@'
TOKEN_SOAK_ENV='@SOAK_ENV_FILE@'
UNITS=(trading-heartbeat.service trading-heartbeat.timer)
TIMER_UNIT=trading-heartbeat.timer
# The collector's default URL file: the paper target must never use it.
COLLECTOR_URL_FILE=$DEFAULT_URL_FILE
# Which check this run serves (--target); the collector is the default and is unchanged.
TARGET=collector
PROBE_LABEL=collector
URL_FILE_ENV_NAME=HEARTBEAT_URL_FILE
TARGET_ARGS=
SOAK_ENV_FILE=

FAIL_PING=0
SET_URL=0
INSTALL_TIMER=0
INTERVAL_GIVEN=0
INTERVAL=
URL_FILE_FLAG=
STEP_TIMEOUT=
COMPOSE=()

usage() {
  awk 'NR >= 3 && /^#/ { print; next } NR >= 3 { exit }' "${BASH_SOURCE[0]}" |
    sed 's/^# \{0,1\}//' >&2
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
      --set-url) SET_URL=1 ;;
      --install-timer) INSTALL_TIMER=1 ;;
      --interval-seconds)
        (($# >= 2)) || usage_error "--interval-seconds needs a number of seconds"
        INTERVAL_GIVEN=1
        INTERVAL=$2
        shift
        ;;
      --target)
        (($# >= 2)) || usage_error "--target needs collector, paper or live"
        TARGET=$2
        shift
        ;;
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
  apply_target
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
  if ((SET_URL && INSTALL_TIMER)); then
    usage_error "--set-url and --install-timer cannot be combined"
  fi
  if ((INTERVAL_GIVEN && !INSTALL_TIMER)); then
    usage_error "--interval-seconds is only valid with --install-timer"
  fi
  if ((INSTALL_TIMER)); then
    ((INTERVAL_GIVEN)) || usage_error "--install-timer needs --interval-seconds N (the operator's value; no default exists)"
    [[ $INTERVAL =~ ^[1-9][0-9]*$ ]] || usage_error "--interval-seconds must be a positive integer"
  fi
  local candidate
  for candidate in "$URL_FILE_FLAG" "${!URL_FILE_ENV_NAME:-}"; do
    if [[ -n $candidate && ! $candidate =~ $UNIT_PATH_PATTERN ]]; then
      usage_error "a URL file path must be absolute and hold only letters, digits and . _ / + = , ~ -"
    fi
  done
  local chosen_url_file
  chosen_url_file="$(url_file_path)"
  if [[ $TARGET != live && $chosen_url_file == "$LIVE_URL_FILE" ]]; then
    usage_error "the live heartbeat has its own URL file; the $TARGET heartbeat never uses $LIVE_URL_FILE"
  fi
  if [[ $TARGET == live ]]; then
    if [[ $chosen_url_file == "$COLLECTOR_URL_FILE" || $chosen_url_file == "$PAPER_URL_FILE" ]]; then
      usage_error "the live heartbeat has its own URL file; it never uses the collector's $COLLECTOR_URL_FILE or the paper's $PAPER_URL_FILE"
    fi
    if [[ -n $SOAK_ENV_FILE ]]; then
      usage_error "--soak-env-file is only valid with --target paper --install-timer"
    fi
  elif [[ $TARGET == paper ]]; then
    if [[ $chosen_url_file == "$COLLECTOR_URL_FILE" ]]; then
      usage_error "the paper heartbeat has its own URL file; it never uses the collector's $COLLECTOR_URL_FILE"
    fi
    if ((INSTALL_TIMER)); then
      [[ -n $SOAK_ENV_FILE ]] || usage_error "--target paper --install-timer needs --soak-env-file PATH (the soak env file of deploy/compose-soak.sh)"
      [[ $SOAK_ENV_FILE =~ $UNIT_PATH_PATTERN ]] || usage_error "--soak-env-file must be absolute and hold only letters, digits and . _ / + = , ~ -"
    elif [[ -n $SOAK_ENV_FILE ]]; then
      usage_error "--soak-env-file is only valid with --target paper --install-timer"
    fi
  elif [[ -n $SOAK_ENV_FILE ]]; then
    usage_error "--soak-env-file is only valid with --target paper --install-timer"
  fi
}

# apply_target: select the probe, the URL source and the units of the chosen check.
apply_target() {
  case $TARGET in
    collector) ;;
    paper)
      SERVICE=paper
      PROBE_LABEL="paper liveness"
      DEFAULT_URL_FILE=$PAPER_URL_FILE
      CREDENTIAL_NAME=heartbeat-paper-url
      URL_FILE_ENV_NAME=HEARTBEAT_PAPER_URL_FILE
      UNITS=(trading-soak-paper-heartbeat.service trading-soak-paper-heartbeat.timer)
      TIMER_UNIT=trading-soak-paper-heartbeat.timer
      TARGET_ARGS="--target paper "
      ;;
    live)
      SERVICE=live
      PROBE_LABEL="live liveness"
      DEFAULT_URL_FILE=$LIVE_URL_FILE
      CREDENTIAL_NAME=heartbeat-live-url
      URL_FILE_ENV_NAME=HEARTBEAT_LIVE_URL_FILE
      UNITS=(trading-live-heartbeat.service trading-live-heartbeat.timer)
      TIMER_UNIT=trading-live-heartbeat.timer
      TARGET_ARGS="--target live "
      ;;
    *) usage_error "--target must be collector, paper or live" ;;
  esac
}

# url_file_path: the URL file path without the test prefix (the value a unit must carry).
url_file_path() {
  if [[ -n $URL_FILE_FLAG ]]; then
    printf '%s' "$URL_FILE_FLAG"
  elif [[ -n ${!URL_FILE_ENV_NAME:-} ]]; then
    printf '%s' "${!URL_FILE_ENV_NAME}"
  else
    printf '%s' "$DEFAULT_URL_FILE"
  fi
}

# resolve_url_source: sets URL_SOURCE (a file path) and URL_IS_CREDENTIAL (1 for the systemd
# credential, which systemd delivers as a private copy and whose mode is not ours to judge).
resolve_url_source() {
  URL_IS_CREDENTIAL=0
  if [[ -n ${CREDENTIALS_DIRECTORY:-} && -e ${CREDENTIALS_DIRECTORY}/$CREDENTIAL_NAME ]]; then
    URL_SOURCE="${CREDENTIALS_DIRECTORY}/$CREDENTIAL_NAME"
    URL_IS_CREDENTIAL=1
  else
    URL_SOURCE="$(p "$(url_file_path)")"
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

# run_once: probe the collector (or the paper or live runtime), then ping according to the verdict.
run_once() {
  load_url
  compose_init
  if ((!DRY_RUN)); then
    require_cmd timeout
    require_cmd curl
  fi

  local probe_ok=0
  if [[ $TARGET == paper ]]; then
    # The soak project only, through its wrapper; the read-only liveness probe (plan 16-56).
    if run timeout "$STEP_TIMEOUT" bash "$SCRIPT_DIR/compose-soak.sh" exec -T "$SERVICE" "$PY" -m src.paper.runtime --liveness; then
      probe_ok=1
    fi
  elif [[ $TARGET == live ]]; then
    # The main stack's live service; the read-only liveness probe (plans 24-11 and 24-24).
    if run timeout "$STEP_TIMEOUT" "${COMPOSE[@]}" exec -T "$SERVICE" "$PY" -m src.live.runtime --liveness; then
      probe_ok=1
    fi
  elif run timeout "$STEP_TIMEOUT" "${COMPOSE[@]}" exec -T "$SERVICE" "$PY" -m src.data.collector --healthcheck; then
    probe_ok=1
  fi

  if ((probe_ok)); then
    deliver success "" || return 3
    return 0
  fi
  if ((FAIL_PING)); then
    log "heartbeat: $PROBE_LABEL probe failed; sending a fail ping"
    deliver fail /fail || true
  else
    log "heartbeat: $PROBE_LABEL probe failed; no ping sent"
  fi
  return 1
}

require_root() {
  if [[ -z ${TRADING_ROOT_PREFIX:-} && ${EUID} -ne 0 ]]; then
    die "$1 must run as root (sudo deploy/heartbeat.sh $1 ...)"
  fi
}

# set_url: read one line from standard input without echo and store it, mode 0600. The value is
# never printed; it is passed to write_if_changed as a shell argument, never to a command.
set_url() {
  require_root --set-url
  local line="" path
  path="$(p "$(url_file_path)")"
  if [[ -t 0 ]]; then
    printf 'Paste the ping URL (input is hidden): ' >&2
  fi
  IFS= read -rs line || [[ -n $line ]] || url_die "no ping URL was provided on standard input"
  if [[ -t 0 ]]; then
    printf '\n' >&2
  fi
  validate_url_text "$line" || url_die "the input is not exactly one https URL of allowed characters (content not shown)"
  write_if_changed "$path" "$line" 0600
  if ((DRY_RUN)); then
    log "heartbeat: would store the ping URL in $path (value not shown)"
    return 0
  fi
  chmod 0600 -- "$path"
  if ((WROTE)); then
    log "heartbeat: ping URL stored in $path (value not shown)"
  else
    log "heartbeat: ping URL in $path unchanged (value not shown)"
  fi
}

# install_timer: write the two units with the operator's values and enable the timer.
install_timer() {
  require_root --install-timer
  [[ $REPO_ROOT != *[[:space:]]* ]] || die "checkout path contains whitespace: $REPO_ROOT"
  # a pattern replacement must not treat an ampersand in a path as the matched text
  shopt -u patsub_replacement 2>/dev/null || true
  local unit_url_file url_path unit_dir content changed=0 unit
  unit_url_file="$(url_file_path)"
  url_path="$(p "$unit_url_file")"
  if [[ ! -f $url_path ]]; then
    if ((DRY_RUN)); then
      warn "no ping URL file at $url_path yet; run 'sudo deploy/heartbeat.sh ${TARGET_ARGS}--set-url' before the real install"
    else
      url_die "no ping URL file at $url_path; run 'sudo deploy/heartbeat.sh ${TARGET_ARGS}--set-url' first"
    fi
  fi
  if [[ $TARGET == paper && ! -f "$(p "$SOAK_ENV_FILE")" ]]; then
    if ((DRY_RUN)); then
      warn "no soak env file at $SOAK_ENV_FILE yet; create it from deploy/soak.env.example before the real install"
    else
      die "no soak env file at $SOAK_ENV_FILE; create it from deploy/soak.env.example first"
    fi
  fi
  unit_dir="$(p /etc/systemd/system)"
  for unit in "${UNITS[@]}"; do
    [[ -f $SCRIPT_DIR/systemd/$unit ]] || die "missing unit template: deploy/systemd/$unit"
    content="$(<"$SCRIPT_DIR/systemd/$unit")"
    content="${content//"$TOKEN_DIR"/$REPO_ROOT}"
    content="${content//"$TOKEN_URL_FILE"/$unit_url_file}"
    content="${content//"$TOKEN_FAIL_PING"/$FAIL_PING}"
    content="${content//"$TOKEN_INTERVAL"/$INTERVAL}"
    content="${content//"$TOKEN_SOAK_ENV"/$SOAK_ENV_FILE}"
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
    printf 'ERROR: refusing to run under xtrace: it would print the ping URL\n' >&2
    exit 2
  fi
  parse_args "$@"
  export DRY_RUN
  cd "$REPO_ROOT"
  if ((SET_URL)); then
    set_url
    return 0
  fi
  if ((INSTALL_TIMER)); then
    install_timer
    return 0
  fi
  run_once
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
