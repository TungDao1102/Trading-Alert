#!/usr/bin/env bash
set -Eeuo pipefail
# List the pinned images, tool versions and GitHub Actions of this checkout, or ask the registries
# and GitHub whether any pin has moved (13.1-11, D-05, D-26). READ-ONLY: it never edits a file.
# A bump is a deliberate, reviewed commit across every file plus the pin table in
# docs/operations/RUNBOOK.md section 16; nothing here is automatic.
#
# Usage:
#   deploy/refresh-pins.sh --list     offline: print every pin parsed from the repository files
#   deploy/refresh-pins.sh --lookup   online: print the registry's current index digest for each
#                                     image tag and the commit each action tag points at now, and
#                                     whether it differs from the pin (needs curl and git)
#
# --list prints one `<name>:<tag>@sha256:<digest>` line per image, `uv-version X`,
# `python-version X` and one `<owner/repo>@<sha> <tag>` line per action.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE=""

usage() {
  sed -n '3,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
}

usage_error() {
  usage
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --list) MODE=list ;;
      --lookup) MODE=lookup ;;
      -h | --help)
        usage
        exit 0
        ;;
      *) usage_error "unknown option: $1" ;;
    esac
    shift
  done
  [[ -n $MODE ]] || usage_error "give --list or --lookup"
}

# read_clean FILE: the file with any CR removed (a Windows working copy may have CRLF).
read_clean() {
  tr -d '\r' <"$1"
}

# image_pins: one `<ref> <digest>` line per pinned image reference in the Dockerfile and the
# compose file; <ref> is exactly as written before the `@`, e.g. ghcr.io/astral-sh/uv:0.12.21.
image_pins() {
  local file
  for file in Dockerfile docker-compose.yml; do
    read_clean "$REPO_ROOT/$file" |
      sed -nE 's~^[[:space:]]*(FROM|image:)[[:space:]]+([^[:space:]@]+)@(sha256:[0-9a-f]{64}).*~\2 \3~p'
  done | awk '!seen[$1]++'
}

# action_pins: one `<owner/repo> <sha> <tag>` line per distinct pinned action over the workflows.
action_pins() {
  local file
  for file in "$REPO_ROOT"/.github/workflows/*.yml; do
    read_clean "$file" |
      sed -nE 's~^.*uses:[[:space:]]*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(/[^@[:space:]]*)?@([0-9a-f]{40})[[:space:]]*#[[:space:]]*(v[0-9A-Za-z.]+).*~\1 \3 \4~p'
  done | sort -u
}

uv_version() {
  read_clean "$REPO_ROOT/.github/workflows/ci.yml" |
    sed -nE 's~^[[:space:]]+version:[[:space:]]*"([^"]+)".*~\1~p' | head -n 1
}

python_version() {
  read_clean "$REPO_ROOT/.python-version" | tr -d '[:space:]'
}

# split_ref REF: sets REF_NAME (last path component), REF_TAG and REF_REPO (path without tag).
split_ref() {
  REF_REPO="${1%%:*}"
  REF_TAG="${1#*:}"
  REF_NAME="${REF_REPO##*/}"
}

do_list() {
  local ref digest repo sha tag
  while read -r ref digest; do
    split_ref "$ref"
    printf '%s:%s@%s\n' "$REF_NAME" "$REF_TAG" "$digest"
  done < <(image_pins)
  printf 'uv-version %s\n' "$(uv_version)"
  printf 'python-version %s\n' "$(python_version)"
  while read -r repo sha tag; do
    printf '%s@%s %s\n' "$repo" "$sha" "$tag"
  done < <(action_pins)
}

# registry_digest REF: the index digest the registry serves for the tag, via the anonymous token
# and a HEAD request (no daemon needed). Prints nothing when the lookup fails.
registry_digest() {
  local ref=$1 host token_url manifest_url token
  split_ref "$ref"
  if [[ $REF_REPO == ghcr.io/* ]]; then
    local path="${REF_REPO#ghcr.io/}"
    host=ghcr.io
    token_url="https://ghcr.io/token?scope=repository:${path}:pull"
    manifest_url="https://ghcr.io/v2/${path}/manifests/${REF_TAG}"
  else
    local path="$REF_REPO"
    [[ $path == */* ]] || path="library/$path"
    host=registry-1.docker.io
    token_url="https://auth.docker.io/token?service=registry.docker.io&scope=repository:${path}:pull"
    manifest_url="https://${host}/v2/${path}/manifests/${REF_TAG}"
  fi
  token="$(curl -fsS "$token_url" 2>/dev/null |
    sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1 || true)"
  [[ -n $token ]] || return 0
  curl -fsSI \
    -H "Authorization: Bearer $token" \
    -H "Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json" \
    "$manifest_url" 2>/dev/null | tr -d '\r' |
    awk 'tolower($1) == "docker-content-digest:" { print $2; exit }' || true
}

# action_sha REPO TAG: the commit the tag points at (the peeled commit of an annotated tag).
action_sha() {
  local out peeled plain
  out="$(GIT_TERMINAL_PROMPT=0 git ls-remote "https://github.com/$1" "refs/tags/$2" "refs/tags/$2^{}" 2>/dev/null || true)"
  peeled="$(awk '$2 ~ /\^\{\}$/ { print $1; exit }' <<<"$out")"
  plain="$(awk 'NR == 1 { print $1 }' <<<"$out")"
  printf '%s' "${peeled:-$plain}"
}

# report KIND LABEL PINNED CURRENT: one line; sets FAILED when the lookup returned nothing.
FAILED=0
report() {
  local kind=$1 label=$2 pinned=$3 current=$4 verdict
  if [[ -z $current ]]; then
    verdict="lookup failed"
    FAILED=1
  elif [[ $current == "$pinned" ]]; then
    verdict="unchanged"
  else
    verdict="MOVED"
  fi
  printf '%s %s pinned=%s current=%s %s\n' "$kind" "$label" "$pinned" "${current:-none}" "$verdict"
}

do_lookup() {
  require_cmd curl
  require_cmd git
  local ref digest repo sha tag
  while read -r ref digest; do
    report image "$ref" "$digest" "$(registry_digest "$ref")"
  done < <(image_pins)
  while read -r repo sha tag; do
    report action "$repo@$tag" "$sha" "$(action_sha "$repo" "$tag")"
  done < <(action_pins)
  log "read-only: nothing was edited. To bump, change every file and the RUNBOOK section 16 table in one reviewed commit."
  return "$FAILED"
}

main() {
  parse_args "$@"
  if [[ $MODE == list ]]; then
    do_list
  else
    do_lookup
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
