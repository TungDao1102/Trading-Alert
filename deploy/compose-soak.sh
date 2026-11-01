#!/usr/bin/env bash
set -Eeuo pipefail
# Run docker compose against the soak project only, and never let it drop the soak volumes
# (plan 16-32, D-32; D061 hosts: the volume removal form of the down command is never run on
# the soak project).
#
# Usage:
#   deploy/compose-soak.sh COMPOSE_ARGS...      e.g. up -d, ps, logs paper, down
#   TRADING_ENV_FILE=/path/to/soak.env deploy/compose-soak.sh --profile paper up -d
#
# Every call runs as `docker compose -p trading-soak ...`, so the volumes are trading-soak_pgdata
# and so on, apart from the development stack (project trading) and its test databases.
# `down` with -v or --volumes is refused wherever the flag appears and however the project name
# was given (the -p flag, the project-name flag or COMPOSE_PROJECT_NAME). A -p or --project-name
# that names another project is refused too, so this wrapper cannot be pointed elsewhere by
# mistake. TRADING_ENV_FILE is honoured (see compose_init in lib.sh); DRY_RUN=1 only prints.
#
# One soak env file (plan 24-36, D-29, WR-06): the compose file gives the paper services a paper
# env file (TRADING_PAPER_ENV_FILE) and the backup and ops services a backup env file
# (TRADING_BACKUP_ENV_FILE), on top of the shared one. When TRADING_ENV_FILE is set this wrapper
# points both at it, so the soak keeps its single operator file and never reads the checkout's own
# .env.paper or .env.backup (which hold the real shadow bot token and the real backup secrets).
#
# The guard covers this wrapper. It cannot stop a hand-typed raw compose command: the runbook
# and tests/test_soak_compose.py therefore forbid one, and the test scans the runbook code
# blocks and deploy/*.sh for it.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

SOAK_PROJECT=trading-soak

# soak_args_remove_volumes ARGS...: true (0) when the arguments are a `down` that also asks to
# remove volumes: -v, a short-flag cluster containing v (-tv), --volumes or --volumes=...
soak_args_remove_volumes() {
  local arg seen_down=0 volumes=0
  for arg in "$@"; do
    case $arg in
      down) seen_down=1 ;;
      --volumes | --volumes=*) volumes=1 ;;
      --*) ;;
      -*v*) volumes=1 ;;
      *) ;;
    esac
  done
  [[ $seen_down == 1 && $volumes == 1 ]]
}

# soak_args_name_other_project ARGS...: true (0) when a -p or --project-name flag names a project
# other than the soak project.
soak_args_name_other_project() {
  local arg expect_value=0
  for arg in "$@"; do
    if [[ $expect_value == 1 ]]; then
      expect_value=0
      [[ $arg == "$SOAK_PROJECT" ]] || return 0
      continue
    fi
    case $arg in
      -p | --project-name) expect_value=1 ;;
      --project-name=*) [[ ${arg#--project-name=} == "$SOAK_PROJECT" ]] || return 0 ;;
      *) ;;
    esac
  done
  # A trailing flag without a value is left to compose to reject.
  return 1
}

main() {
  if soak_args_remove_volumes "$@"; then
    die "refused: down -v on the soak project ($SOAK_PROJECT). Its database volume holds soak evidence; remove volumes by hand on the host only after a restore drill, never through this wrapper."
  fi
  if soak_args_name_other_project "$@"; then
    die "refused: this wrapper drives only the project $SOAK_PROJECT; drop the -p / --project-name flag."
  fi
  export COMPOSE_PROJECT_NAME="$SOAK_PROJECT"
  if [[ -n ${TRADING_ENV_FILE:-} ]]; then
    export TRADING_PAPER_ENV_FILE="$TRADING_ENV_FILE"
    export TRADING_BACKUP_ENV_FILE="$TRADING_ENV_FILE"
  fi
  compose_init
  # Put the project flag right after `docker compose`; compose_init may have added --env-file.
  COMPOSE=(docker compose -p "$SOAK_PROJECT" "${COMPOSE[@]:2}")
  run "${COMPOSE[@]}" "$@"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  main "$@"
fi
