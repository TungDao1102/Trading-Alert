#!/usr/bin/env bash
set -Eeuo pipefail
# Update the running stack to a git ref, or roll back to the images that ran before (13.1-10, D-16).
#
# Usage:
#   deploy/update.sh --ref REF [--skip-backup] [--dry-run]
#   deploy/update.sh --rollback [--dry-run]
#
# --ref refuses a dirty working tree, records the current commit and the IDs of both images in
# .deploy/last-good.env, runs deploy/backup.sh (unless --skip-backup; a failing backup stops the
# update), tags both images :rollback, fetches, checks out REF detached, builds and starts the
# stack.
# --rollback checks out the recorded commit, tags the :rollback images back to the active tag,
# compares the image IDs with the recorded ones (a mismatch aborts), and starts with --no-build.
# A schema migration that the newer version applied is NOT undone by a code rollback: restore
# from a backup (deploy/restore.sh) if the older code cannot read the migrated database.
#
# COMPOSE_PROJECT_NAME, TRADING_ENV_FILE and IMAGE_TAG (default dev) are honoured from the
# environment. TRADING_DEPLOY_STATE_DIR replaces .deploy (tests).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TAG="${IMAGE_TAG:-dev}"
APP_REPO=trading-alert
OPS_REPO=trading-alert-ops

REF=""
ROLLBACK=0
SKIP_BACKUP=0
STATE_DIR=""
STATE_FILE=""
COMPOSE=()

usage() {
  sed -n '3,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
}

usage_error() {
  usage
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --ref)
        (($# >= 2)) || usage_error "option --ref needs a value"
        REF="$2"
        shift
        ;;
      --rollback) ROLLBACK=1 ;;
      --skip-backup) SKIP_BACKUP=1 ;;
      --dry-run) DRY_RUN=1 ;;
      -h | --help)
        usage
        exit 0
        ;;
      *) usage_error "unknown option: $1" ;;
    esac
    shift
  done
  if ((ROLLBACK)) && [[ -n $REF ]]; then
    usage_error "--ref and --rollback cannot be combined"
  fi
  if ((!ROLLBACK)) && [[ -z $REF ]]; then
    usage_error "give --ref REF or --rollback"
  fi
  if ((ROLLBACK)) && ((SKIP_BACKUP)); then
    usage_error "--skip-backup only applies to --ref"
  fi
  if [[ $REF == -* ]]; then
    usage_error "a ref must not start with a dash: $REF"
  fi
}

# image_id TAG: the image ID behind a tag, empty when the tag does not exist.
image_id() {
  docker image inspect --format '{{.Id}}' "$1" 2>/dev/null || true
}

require_clean_tree() {
  local dirty
  dirty="$(git status --porcelain --untracked-files=no)"
  [[ -z $dirty ]] || die "the working tree has uncommitted changes; commit or discard them first"
}

# state_value KEY: the value recorded for KEY in the state file (the file is parsed, never sourced).
state_value() {
  local line
  line="$(grep -E "^$1=" "$STATE_FILE" | head -n 1 || true)"
  printf '%s' "${line#*=}"
}

record_state() {
  local sha app_id ops_id
  sha="$(git rev-parse HEAD)"
  app_id="$(image_id "$APP_REPO:$TAG")"
  ops_id="$(image_id "$OPS_REPO:$TAG")"
  if [[ $DRY_RUN == 1 ]]; then
    : "${app_id:=<image id of $APP_REPO:$TAG>}"
    : "${ops_id:=<image id of $OPS_REPO:$TAG>}"
  else
    [[ -n $app_id && -n $ops_id ]] ||
      die "images $APP_REPO:$TAG and $OPS_REPO:$TAG must exist locally so they can be rolled back to"
  fi
  write_if_changed "$STATE_FILE" "GIT_SHA=$sha
APP_IMAGE_ID=$app_id
OPS_IMAGE_ID=$ops_id" 0600
}

do_update() {
  require_clean_tree
  record_state
  if ((!SKIP_BACKUP)); then
    run bash "$SCRIPT_DIR/backup.sh"
  fi
  run docker tag "$APP_REPO:$TAG" "$APP_REPO:rollback"
  run docker tag "$OPS_REPO:$TAG" "$OPS_REPO:rollback"
  run git fetch --tags origin
  run git checkout --detach "$REF"
  run "${COMPOSE[@]}" --profile ops build
  run "${COMPOSE[@]}" up -d
  log "updated to $REF; undo with: deploy/update.sh --rollback"
}

# verify_image TAG EXPECTED_ID: abort unless the tag points at the recorded image.
verify_image() {
  local actual
  if [[ $DRY_RUN == 1 ]]; then
    printf '+ verify image id of %s equals the recorded %s\n' "$1" "$2"
    return 0
  fi
  actual="$(image_id "$1")"
  [[ $actual == "$2" ]] || die "image $1 is ${actual:-missing}, recorded was $2; refusing to roll back"
}

do_rollback() {
  [[ -f $STATE_FILE ]] || die "no rollback state at $STATE_FILE; nothing to roll back to"
  local sha app_id ops_id
  sha="$(state_value GIT_SHA)"
  app_id="$(state_value APP_IMAGE_ID)"
  ops_id="$(state_value OPS_IMAGE_ID)"
  [[ $sha =~ ^[0-9a-f]{40}$ ]] || die "$STATE_FILE has no valid GIT_SHA"
  [[ $app_id =~ ^sha256:[0-9a-f]{64}$ ]] || die "$STATE_FILE has no valid APP_IMAGE_ID"
  [[ $ops_id =~ ^sha256:[0-9a-f]{64}$ ]] || die "$STATE_FILE has no valid OPS_IMAGE_ID"
  require_clean_tree
  # The :rollback tags must still hold the recorded images before anything is changed.
  verify_image "$APP_REPO:rollback" "$app_id"
  verify_image "$OPS_REPO:rollback" "$ops_id"
  run git checkout --detach "$sha"
  run docker tag "$APP_REPO:rollback" "$APP_REPO:$TAG"
  run docker tag "$OPS_REPO:rollback" "$OPS_REPO:$TAG"
  verify_image "$APP_REPO:$TAG" "$app_id"
  verify_image "$OPS_REPO:$TAG" "$ops_id"
  run "${COMPOSE[@]}" up -d --no-build
  warn "a database schema migration applied by the newer version is NOT undone by this rollback;" \
    "if the older code cannot read the migrated schema, restore with deploy/restore.sh"
}

main() {
  parse_args "$@"
  export DRY_RUN
  cd "$REPO_ROOT"
  compose_init
  STATE_DIR="${TRADING_DEPLOY_STATE_DIR:-$REPO_ROOT/.deploy}"
  STATE_FILE="$STATE_DIR/last-good.env"
  if ((ROLLBACK)); then
    do_rollback
  else
    do_update
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
