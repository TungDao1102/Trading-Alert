#!/usr/bin/env bash
set -Eeuo pipefail
# Build the soak images on this host from a clean, committed tree, tag them with the commit and
# record the commit and the image ids (plan 16-33, D-32, decision 16-DEC-Q-I: host-build-recorded).
#
# Usage:
#   deploy/soak-image.sh [--dry-run]
#
# It refuses a working tree with any uncommitted change, tracked or untracked, because the build
# context is the working tree and an uncommitted file would reach the image without a commit to
# name it. It then builds trading-alert:<commit> and trading-alert-ops:<commit> (the full 40
# character commit id) with the soak wrapper (project trading-soak), checks that the tree and HEAD
# did not change during the build, reads the two image ids and writes them to
# .deploy/soak-image.env (mode 0600; the previous record is kept as soak-image.env.prev and each
# build is appended to soak-image.history). The soak is then started with IMAGE_TAG=<commit>, see
# RUNBOOK 20.6. The record has the key layout of update.sh's last-good.env (GIT_SHA, APP_IMAGE_ID,
# OPS_IMAGE_ID) plus IMAGE_TAG, but it is a separate file: update.sh overwrites last-good.env on
# every --ref run and this file is the evidence of which image the soak ran.
#
# Before the record is written, the in-image check (plan 16-55, review B2-CR-05) runs inside the
# built trading-alert:<commit> image with no network: scripts/check_image_paths.py loads every
# allowlisted parameter set from /app/params and the runtime configuration named by
# IN_IMAGE_RUNTIME_CONFIG. A failure exits non-zero and nothing is recorded.
#
# --dry-run (or DRY_RUN=1) prints the commands and the record and writes nothing; the dirty-tree
# refusal still applies. TRADING_DEPLOY_STATE_DIR replaces .deploy (tests).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_REPO=trading-alert
OPS_REPO=trading-alert-ops
# The ratified runtime configuration inside the image: a fixed name of the committed file, not a
# user number. The soak env file sets PAPER_RUNTIME_CONFIG to the same path (RUNBOOK 20.6); a move
# to another configuration file changes this one line.
IN_IMAGE_RUNTIME_CONFIG=/app/config/paper/paper-runtime-v2.toml

usage() {
  sed -n '3,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
}

usage_error() {
  usage
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --dry-run) DRY_RUN=1 ;;
      -h | --help)
        usage
        exit 0
        ;;
      *) usage_error "unknown option: $1" ;;
    esac
    shift
  done
}

# require_clean_tree: abort when anything is uncommitted. Untracked files count: they are part of
# the build context unless ignored. Ignored files (for example .env) do not appear here.
require_clean_tree() {
  local dirty
  dirty="$(git status --porcelain --untracked-files=all)"
  [[ -z $dirty ]] || die "the working tree has uncommitted changes (tracked or untracked); the soak image is built only from a clean commit. Commit or discard them first"
}

# image_id TAG: the image ID behind a tag, empty when the tag does not exist.
image_id() {
  docker image inspect --format '{{.Id}}' "$1" 2>/dev/null || true
}

main() {
  parse_args "$@"
  export DRY_RUN
  cd "$REPO_ROOT"
  require_cmd git
  require_clean_tree

  local sha state_dir state_file app_id ops_id content utc
  sha="$(git rev-parse --verify HEAD)"
  [[ $sha =~ ^[0-9a-f]{40}$ ]] || die "HEAD is not a 40 character commit id: $sha"
  state_dir="${TRADING_DEPLOY_STATE_DIR:-$REPO_ROOT/.deploy}"
  state_file="$state_dir/soak-image.env"

  printf 'commit %s\n' "$sha"
  printf 'image %s:%s\n' "$APP_REPO" "$sha"
  printf 'image %s:%s\n' "$OPS_REPO" "$sha"

  # IMAGE_TAG feeds the image names of docker-compose.yml; the soak wrapper pins the project.
  export IMAGE_TAG="$sha"
  run bash "$SCRIPT_DIR/compose-soak.sh" --profile ops build

  if [[ $DRY_RUN == 1 ]]; then
    app_id="<image id of $APP_REPO:$sha>"
    ops_id="<image id of $OPS_REPO:$sha>"
  else
    require_clean_tree
    [[ "$(git rev-parse --verify HEAD)" == "$sha" ]] || die "HEAD moved during the build; nothing recorded"
    app_id="$(image_id "$APP_REPO:$sha")"
    ops_id="$(image_id "$OPS_REPO:$sha")"
    [[ $app_id =~ ^sha256:[0-9a-f]{64}$ ]] || die "image $APP_REPO:$sha is missing after the build"
    [[ $ops_id =~ ^sha256:[0-9a-f]{64}$ ]] || die "image $OPS_REPO:$sha is missing after the build"
  fi

  # The in-image check: the image must admit its allowlisted set and load its configuration.
  run docker run --rm --network none --env "PAPER_RUNTIME_CONFIG=$IN_IMAGE_RUNTIME_CONFIG"     --entrypoint /app/.venv/bin/python "$APP_REPO:$sha"     -m scripts.check_image_paths --root /app ||
    die "the in-image check failed in $APP_REPO:$sha (parameter set or runtime configuration not loadable); nothing recorded"

  content="GIT_SHA=$sha
IMAGE_TAG=$sha
APP_IMAGE_ID=$app_id
OPS_IMAGE_ID=$ops_id"
  printf 'record %s:\n%s\n' "$state_file" "$content"

  if [[ $DRY_RUN != 1 && -f $state_file ]] && ! cmp -s "$state_file" <(printf '%s\n' "$content"); then
    cp -p "$state_file" "$state_file.prev"
  fi
  write_if_changed "$state_file" "$content" 0600
  if [[ $DRY_RUN != 1 ]]; then
    utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '%s GIT_SHA=%s APP_IMAGE_ID=%s OPS_IMAGE_ID=%s\n' "$utc" "$sha" "$app_id" "$ops_id" \
      >>"$state_dir/soak-image.history"
  fi
  log "soak image recorded; start the soak with IMAGE_TAG=$sha (RUNBOOK 20.6)"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
