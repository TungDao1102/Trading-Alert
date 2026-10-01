#!/usr/bin/env bash
# Shared helpers for the deploy/*.sh scripts. Source this file; never execute it.
#
# Test seams (used by tests/test_bootstrap.py, harmless on a real host):
#   TRADING_ROOT_PREFIX  prefix for every absolute system path (see p)
#   OS_RELEASE_FILE      replaces /etc/os-release
#   DRY_RUN=1            run prints the command it would execute and skips it
set -Eeuo pipefail

DRY_RUN="${DRY_RUN:-0}"
# Set by write_if_changed: 1 when the last call changed (or, in dry-run, would change) the file.
WROTE=0

log() { printf '%s\n' "$*" >&2; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# p PATH: prefix an absolute system path with TRADING_ROOT_PREFIX (empty on a real host).
p() { printf '%s%s' "${TRADING_ROOT_PREFIX:-}" "$1"; }

# run CMD...: announce a mutation as "+ cmd" on stdout, then execute it unless DRY_RUN=1.
# Only commands without secret arguments may go through run (the line is printed).
run() {
  printf '+ %s\n' "$*"
  if [[ "${DRY_RUN}" == 1 ]]; then
    return 0
  fi
  "$@"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

# os_release_get KEY: value of KEY from the os-release file (surrounding double quotes removed).
os_release_get() {
  local file="${OS_RELEASE_FILE:-/etc/os-release}"
  [[ -r $file ]] || die "cannot read os-release file: $file"
  awk -F= -v key="$1" '
    $1 == key {
      v = substr($0, length(key) + 2)
      sub(/\r$/, "", v)
      sub(/^"/, "", v)
      sub(/"$/, "", v)
      print v
      exit
    }' "$file"
}

# read_os_release: sets OS_ID, OS_VERSION_ID and OS_CODENAME (UBUNTU_CODENAME wins on Ubuntu).
read_os_release() {
  OS_ID="$(os_release_get ID)"
  OS_VERSION_ID="$(os_release_get VERSION_ID)"
  OS_CODENAME="$(os_release_get UBUNTU_CODENAME)"
  if [[ -z $OS_CODENAME ]]; then
    OS_CODENAME="$(os_release_get VERSION_CODENAME)"
  fi
}

# posix_modes_supported: false under Git Bash / MSYS / Cygwin, where NTFS has no POSIX modes.
posix_modes_supported() {
  case "$(uname -s 2>/dev/null || true)" in
    MINGW* | MSYS* | CYGWIN*) return 1 ;;
    *) return 0 ;;
  esac
}

# pkg_installed PKG: true when dpkg reports the package fully installed.
pkg_installed() {
  # shellcheck disable=SC2016  # ${Status} is dpkg-query's own format syntax
  dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'
}

# write_if_changed PATH CONTENT [MODE]: write CONTENT plus a trailing newline to PATH through a
# temp file in the same directory and an atomic rename, only when the content differs.
# Sets WROTE. Under DRY_RUN=1 it announces "+ write PATH" and writes nothing.
write_if_changed() {
  local path=$1 content=$2 mode="${3:-0644}" tmp
  WROTE=0
  if [[ -f $path ]] && cmp -s "$path" <(printf '%s\n' "$content"); then
    return 0
  fi
  WROTE=1
  printf '+ write %s\n' "$path"
  if [[ "${DRY_RUN}" == 1 ]]; then
    return 0
  fi
  mkdir -p "$(dirname "$path")"
  tmp="$(mktemp "$path.XXXXXX")"
  printf '%s\n' "$content" >"$tmp"
  chmod "$mode" "$tmp"
  mv -f "$tmp" "$path"
}
