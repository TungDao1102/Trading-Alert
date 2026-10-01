#!/usr/bin/env bash
# Host bootstrap for the trading stack: a fresh Ubuntu 22.04/24.04 or Debian 12 host becomes a
# hardened Docker host with the repository checked out and .env in place (D-10, D-11).
# Provider-neutral: plain apt, ufw, sshd, chrony and Docker Engine; no cloud CLI of any kind.
#
# Usage:
#   sudo deploy/bootstrap.sh --secrets-file PATH --repo URL --ref REF \
#        --authorized-keys PATH [--dir /opt/trading] [--user trading] \
#        [--deploy-key PATH] [--max-drift-ms 100] [--dry-run]
#
# --dry-run prints the ordered "+ command" plan and changes nothing. The script is idempotent:
# a second run against an already configured host announces no mutation.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib.sh
source "$SCRIPT_DIR/lib.sh"

# Supported releases as data (D-10); anything else is refused before anything changes.
SUPPORTED_OS=("ubuntu 22.04" "ubuntu 24.04" "debian 12")

SECRETS_FILE=""
REPO_URL=""
REPO_REF=""
INSTALL_DIR="/opt/trading"
TRADING_USER="trading"
AUTH_KEYS_SRC=""
DEPLOY_KEY=""
MAX_DRIFT_MS="100"
USER_HOME=""

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --secrets-file | --repo | --ref | --dir | --user | --authorized-keys | --deploy-key | --max-drift-ms)
        (($# >= 2)) || die "option $1 needs a value"
        case "$1" in
          --secrets-file) SECRETS_FILE="$2" ;;
          --repo) REPO_URL="$2" ;;
          --ref) REPO_REF="$2" ;;
          --dir) INSTALL_DIR="$2" ;;
          --user) TRADING_USER="$2" ;;
          --authorized-keys) AUTH_KEYS_SRC="$2" ;;
          --deploy-key) DEPLOY_KEY="$2" ;;
          --max-drift-ms) MAX_DRIFT_MS="$2" ;;
        esac
        shift 2
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      -h | --help)
        usage
        exit 0
        ;;
      *)
        usage
        die "unknown option: $1"
        ;;
    esac
  done
  [[ -n $SECRETS_FILE ]] || die "--secrets-file is required"
  [[ -n $REPO_REF ]] || die "--ref is required (a tag or commit to deploy)"
  [[ $MAX_DRIFT_MS =~ ^[0-9]+$ ]] || die "--max-drift-ms must be a whole number of milliseconds"
  [[ $TRADING_USER =~ ^[a-z_][a-z0-9_-]*$ ]] || die "--user is not a valid account name"
  [[ $INSTALL_DIR == /* ]] || die "--dir must be an absolute path"
}

# keys_file_has_valid_key FILE: at least one non-comment line that ssh-keygen accepts as a key.
keys_file_has_valid_key() {
  local file=$1 line tmp rc=1
  [[ -s $file ]] || return 1
  tmp="$(mktemp)"
  while IFS= read -r line || [[ -n $line ]]; do
    line="${line%$'\r'}"
    if [[ -z ${line//[[:space:]]/} || $line == \#* ]]; then
      continue
    fi
    printf '%s\n' "$line" >"$tmp"
    if ssh-keygen -l -f "$tmp" >/dev/null 2>&1; then
      rc=0
      break
    fi
  done <"$file"
  rm -f "$tmp"
  return "$rc"
}

resolve_user_home() {
  local entry=""
  entry="$(getent passwd "$TRADING_USER" 2>/dev/null || true)"
  USER_HOME="$(printf '%s' "$entry" | cut -d: -f6)"
  if [[ -z $USER_HOME ]]; then
    USER_HOME="/home/$TRADING_USER"
  fi
}

preflight() {
  read_os_release
  local combo="$OS_ID $OS_VERSION_ID" entry supported=0
  for entry in "${SUPPORTED_OS[@]}"; do
    if [[ $entry == "$combo" ]]; then
      supported=1
    fi
  done
  ((supported)) || die "unsupported OS '$combo' (supported: ${SUPPORTED_OS[*]}); nothing was changed"

  local cmd
  for cmd in awk cmp mktemp ssh-keygen dpkg-query apt-get; do
    require_cmd "$cmd"
  done

  if [[ "$(id -u)" != "0" ]]; then
    if [[ $DRY_RUN == 1 ]]; then
      warn "not running as root: read-only probes may under-report; run the dry run with sudo"
    else
      die "must run as root (use sudo); use --dry-run to preview without root"
    fi
  fi

  [[ -f $SECRETS_FILE && -r $SECRETS_FILE ]] || die "secrets file is not a readable file: $SECRETS_FILE"

  resolve_user_home
  local keys_to_check
  if [[ -n $AUTH_KEYS_SRC ]]; then
    keys_to_check="$AUTH_KEYS_SRC"
  else
    keys_to_check="$(p "$USER_HOME/.ssh/authorized_keys")"
  fi
  keys_file_has_valid_key "$keys_to_check" ||
    die "lock-out guard: no authorized_keys line accepted by ssh-keygen in $keys_to_check; refusing before any step (password SSH would be disabled with no way back in)"

  if [[ -z $REPO_URL && ! -d "$(p "$INSTALL_DIR")/.git" ]]; then
    die "--repo is required: $INSTALL_DIR has no checkout yet"
  fi
}

step_base_packages() {
  run apt-get update
  run apt-get install -y ca-certificates curl git ufw
}

step_docker() {
  run write "$(p /etc/apt/sources.list.d/docker.sources)"
  run apt-get install -y docker-ce
}

step_user() {
  run useradd --create-home --shell /bin/bash "$TRADING_USER"
  run usermod -aG docker "$TRADING_USER"
}

step_ufw() {
  run ufw allow 22/tcp
  run ufw --force enable
}

step_sshd() {
  run write "$(p /etc/ssh/sshd_config.d/00-trading-hardening.conf)"
  run sshd -t
  run systemctl try-reload-or-restart ssh
}

step_chrony() {
  run apt-get install -y chrony
}

step_checkout() {
  run git clone "$REPO_URL" "$(p "$INSTALL_DIR")"
}

step_env() {
  run install -m 0600 "$SECRETS_FILE" "$(p "$INSTALL_DIR/.env")"
}

print_checklist() {
  printf '\nOperator checklist\n'
}

main() {
  parse_args "$@"
  export DRY_RUN
  preflight
  export DEBIAN_FRONTEND=noninteractive
  step_base_packages
  step_docker
  step_user
  step_ufw
  step_sshd
  step_chrony
  step_checkout
  step_env
  print_checklist
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
