#!/usr/bin/env bash
set -Eeuo pipefail
# Run docker compose against the rehearsal project only (plan 16-53, RUNBOOK 20.4, T-16-92).
# The pre-soak SHADOW rehearsal (scripts/shadow_rehearsal.py) runs in its own project, with its
# own database volume and its own env file, and never touches trading-soak or its database.
#
# Usage:
#   TRADING_ENV_FILE=/path/outside/checkout/rehearsal.env deploy/compose-rehearsal.sh [--dry-run] COMPOSE_ARGS...
#   e.g. --dry-run up -d postgres, up -d postgres, ps, logs postgres, stop
#
# Every call runs as `docker compose -p trading-rehearsal ...`, so the volumes are
# trading-rehearsal_pgdata and so on, apart from trading (development) and trading-soak.
# It refuses, before any docker call (exit 1):
#   - TRADING_ENV_FILE unset, not a readable file, or a file inside this checkout;
#   - a variable whose name starts with BINANCE_, in the process environment or in the env file
#     (only the names are printed, never a value);
#   - a -p or --project-name flag that names another project, and an --env-file flag (the env
#     file comes from TRADING_ENV_FILE only);
#   - any running container of the soak project trading-soak (one getUpdates consumer per bot
#     token, and the database port): stop the soak first, `deploy/compose-soak.sh stop`.
# --dry-run (only as the first argument; DRY_RUN=1 does the same) prints the compose command and
# runs no docker at all, so the soak check is only announced. COMPOSE_PROJECT_NAME is overridden.
# TRADING_PAPER_ENV_FILE and TRADING_BACKUP_ENV_FILE (plan 24-36) are pointed at the rehearsal env
# file too, so a rehearsal never reads the checkout's own .env.paper or .env.backup.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

REHEARSAL_PROJECT=trading-rehearsal
SOAK_PROJECT=trading-soak
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
ARGS=()

usage() {
  sed -n '3,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
}

usage_error() {
  usage
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

parse_args() {
  if (($# > 0)); then
    case "$1" in
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      -h | --help)
        usage
        exit 0
        ;;
      *) ;;
    esac
  fi
  (($# > 0)) || usage_error "no docker compose arguments given"
  ARGS=("$@")
}

# rehearsal_args_refused ARGS...: prints the reason and returns 0 when an argument would leave the
# rehearsal project or the single env file.
rehearsal_args_refused() {
  local arg expect_value=0
  for arg in "$@"; do
    if [[ $expect_value == 1 ]]; then
      expect_value=0
      [[ $arg == "$REHEARSAL_PROJECT" ]] || {
        printf 'this wrapper drives only the project %s; drop the -p / --project-name flag' "$REHEARSAL_PROJECT"
        return 0
      }
      continue
    fi
    case $arg in
      -p | --project-name) expect_value=1 ;;
      --project-name=*)
        [[ ${arg#--project-name=} == "$REHEARSAL_PROJECT" ]] || {
          printf 'this wrapper drives only the project %s; drop the -p / --project-name flag' "$REHEARSAL_PROJECT"
          return 0
        }
        ;;
      --env-file | --env-file=*)
        printf 'the env file comes from TRADING_ENV_FILE only; drop the --env-file flag'
        return 0
        ;;
      *) ;;
    esac
  done
  return 1
}

# env_file_inside_checkout FILE: true (0) when FILE lies under this checkout.
env_file_inside_checkout() {
  local dir
  dir="$(cd "$(dirname "$1")" && pwd -P)" || return 1
  [[ $dir == "$REPO_ROOT" || $dir == "$REPO_ROOT"/* ]]
}

# binance_names_present FILE: the BINANCE_ names found in the process environment and in FILE,
# one per line, sorted, without values.
binance_names_present() {
  local line name
  {
    while IFS= read -r name; do
      [[ $name == BINANCE_* ]] && printf '%s\n' "$name"
    done < <(compgen -e)
    while IFS= read -r line || [[ -n $line ]]; do
      if [[ $line =~ ^[[:space:]]*(export[[:space:]]+)?(BINANCE_[A-Za-z0-9_]*)[[:space:]]*= ]]; then
        printf '%s\n' "${BASH_REMATCH[2]}"
      fi
    done <"$1"
  } | sort -u
}

main() {
  parse_args "$@"
  local reason names file name
  if reason="$(rehearsal_args_refused "${ARGS[@]}")"; then
    die "refused: $reason."
  fi

  file="${TRADING_ENV_FILE:-}"
  [[ -n $file ]] || die "refused: TRADING_ENV_FILE is not set; point it at the rehearsal env file (outside the checkout, never the soak env file)."
  [[ -f $file && -r $file ]] || die "refused: TRADING_ENV_FILE is not a readable file."
  if env_file_inside_checkout "$file"; then
    die "refused: the rehearsal env file lies inside this checkout; keep it outside, with mode 0600."
  fi

  names="$(binance_names_present "$file")"
  if [[ -n $names ]]; then
    while IFS= read -r name; do
      printf 'refused: trade-capable variable present: %s\n' "$name" >&2
    done <<<"$names"
    die "refused: a BINANCE_ variable is present (the rehearsal is credential free); remove it from the environment and the env file."
  fi

  if [[ $DRY_RUN == 1 ]]; then
    printf 'note: dry run, docker is not called; a real run first checks that no %s container is running\n' "$SOAK_PROJECT"
  else
    require_cmd docker
    local running
    running="$(docker ps -q --filter "label=com.docker.compose.project=$SOAK_PROJECT")" \
      || die "refused: cannot tell whether $SOAK_PROJECT is running (docker ps failed)."
    [[ -z $running ]] || die "refused: the soak project $SOAK_PROJECT has running containers; stop it first (deploy/compose-soak.sh stop) so the rehearsal shares neither its bot token nor its ports."
  fi

  export COMPOSE_PROJECT_NAME="$REHEARSAL_PROJECT"
  export TRADING_PAPER_ENV_FILE="$file"
  export TRADING_BACKUP_ENV_FILE="$file"
  compose_init
  # Put the project flag right after `docker compose`; compose_init has added --env-file.
  COMPOSE=(docker compose -p "$REHEARSAL_PROJECT" "${COMPOSE[@]:2}")
  run "${COMPOSE[@]}" "${ARGS[@]}"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  main "$@"
fi
