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

APT_UPDATED=0

apt_update_once() {
  if ((APT_UPDATED == 0)); then
    run apt-get update
    APT_UPDATED=1
  fi
}

# apt_install_missing PKG...: install only the packages dpkg does not report as installed.
apt_install_missing() {
  local pkg missing=()
  for pkg in "$@"; do
    if ! pkg_installed "$pkg"; then
      missing+=("$pkg")
    fi
  done
  if ((${#missing[@]} > 0)); then
    apt_update_once
    run apt-get install -y "${missing[@]}"
  fi
}

step_base_packages() {
  apt_install_missing ca-certificates curl git ufw
}

DOCKER_PACKAGES=(docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin)

# Docker's own repository in deb822 form, signed by the keyring Docker documents (T-13.1-22).
docker_sources_content() {
  local arch
  arch="$(dpkg --print-architecture)"
  printf '%s\n' \
    "Types: deb" \
    "URIs: https://download.docker.com/linux/$OS_ID" \
    "Suites: $OS_CODENAME" \
    "Components: stable" \
    "Architectures: $arch" \
    "Signed-By: /etc/apt/keyrings/docker.asc"
}

step_docker() {
  local keyring_dir keyring
  keyring_dir="$(p /etc/apt/keyrings)"
  keyring="$keyring_dir/docker.asc"
  if [[ ! -d $keyring_dir ]]; then
    run install -m 0755 -d "$keyring_dir"
  fi
  if [[ ! -s $keyring ]]; then
    run curl -fsSL "https://download.docker.com/linux/$OS_ID/gpg" -o "$keyring"
    run chmod a+r "$keyring"
  fi
  write_if_changed "$(p /etc/apt/sources.list.d/docker.sources)" "$(docker_sources_content)"
  if ((WROTE)); then
    APT_UPDATED=0
    apt_update_once
  fi
  apt_install_missing "${DOCKER_PACKAGES[@]}"
}

# merge_keys SRC DST: existing DST lines first, then SRC lines not yet present (no duplicates).
merge_keys() {
  local src=$1 dst=$2
  {
    if [[ -f $dst ]]; then
      tr -d '\r' <"$dst"
    fi
    tr -d '\r' <"$src"
  } | awk 'NF && !seen[$0]++'
}

step_user() {
  local ssh_dir keys_dst
  if getent passwd "$TRADING_USER" >/dev/null 2>&1; then
    log "user $TRADING_USER already exists"
  else
    run useradd --create-home --shell /bin/bash "$TRADING_USER"
  fi
  if ! id -nG "$TRADING_USER" 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
    run usermod -aG docker "$TRADING_USER"
  fi
  resolve_user_home
  ssh_dir="$(p "$USER_HOME/.ssh")"
  keys_dst="$ssh_dir/authorized_keys"
  if [[ ! -d $ssh_dir ]]; then
    run install -d -m 0700 -o "$TRADING_USER" -g "$TRADING_USER" "$ssh_dir"
  fi
  if [[ -n $AUTH_KEYS_SRC ]]; then
    write_if_changed "$keys_dst" "$(merge_keys "$AUTH_KEYS_SRC" "$keys_dst")" 0600
    if ((WROTE)); then
      run chown "$TRADING_USER:$TRADING_USER" "$keys_dst"
    fi
  fi
}

# Effective SSH port(s) as sshd itself reports them; never assumed to be 22.
effective_ssh_ports() {
  sshd -T 2>/dev/null | awk '$1 == "port" { print $2 }' || true
}

# ufw: the SSH allow rule is in place before the firewall is enabled (anti lock-out, D-11).
step_ufw() {
  local ports port status ok=1
  ports="$(effective_ssh_ports)"
  if [[ -z $ports ]]; then
    if [[ $DRY_RUN == 1 ]]; then
      ports="<ssh-port>"
    else
      die "lock-out guard: could not read the effective SSH port from 'sshd -T'; not touching the firewall"
    fi
  fi
  status="$(ufw status verbose 2>/dev/null || true)"
  grep -q '^Status: active' <<<"$status" || ok=0
  grep -qi 'deny (incoming)' <<<"$status" || ok=0
  for port in $ports; do
    grep -Eq "^${port}/tcp.*ALLOW" <<<"$status" || ok=0
  done
  if ((ok)); then
    log "ufw already active with default deny incoming and the SSH allow rule"
    return 0
  fi
  run ufw default deny incoming
  run ufw default allow outgoing
  for port in $ports; do
    run ufw allow "${port}/tcp"
  done
  run ufw --force enable
}

# The drop-in is named 00-... because sshd keeps the FIRST value it obtains for a keyword and
# reads sshd_config.d/*.conf in lexical order; cloud images ship 50-cloud-init.conf with
# PasswordAuthentication yes, which a 99- file would lose to.
SSHD_DROPIN_REL=/etc/ssh/sshd_config.d/00-trading-hardening.conf

sshd_dropin_content() {
  printf '%s\n' \
    "# Managed by deploy/bootstrap.sh. Named 00- so it is read before 50-cloud-init.conf." \
    "PasswordAuthentication no" \
    "KbdInteractiveAuthentication no" \
    "PermitRootLogin no" \
    "PubkeyAuthentication yes"
}

# sshd_effective_gaps: print each expectation `sshd -T` does not report (empty output = hardened).
sshd_effective_gaps() {
  local out want
  out="$(sshd -T 2>/dev/null || true)"
  for want in \
    "passwordauthentication no" \
    "kbdinteractiveauthentication no" \
    "permitrootlogin no" \
    "pubkeyauthentication yes"; do
    if ! grep -qix "$want" <<<"$out"; then
      printf '%s\n' "$want"
    fi
  done
}

step_sshd() {
  local cfg dropin gaps
  cfg="$(p /etc/ssh/sshd_config)"
  dropin="$(p "$SSHD_DROPIN_REL")"
  [[ -f $cfg ]] || die "sshd_config not found: $cfg (is openssh-server installed?)"
  grep -Eq '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf' "$cfg" ||
    die "refusing to harden SSH: $cfg has no 'Include /etc/ssh/sshd_config.d/*.conf' line, so a drop-in would be ignored"

  if [[ $DRY_RUN != 1 ]]; then
    keys_file_has_valid_key "$(p "$USER_HOME/.ssh/authorized_keys")" ||
      die "lock-out guard: $TRADING_USER has no valid authorized_keys entry; not writing the SSH drop-in"
  fi

  write_if_changed "$dropin" "$(sshd_dropin_content)" 0644
  if ((WROTE)); then
    if [[ $DRY_RUN == 1 ]]; then
      run sshd -t
      printf '+ sshd -T (assert passwordauthentication no, kbdinteractiveauthentication no, permitrootlogin no)\n'
      run systemctl try-reload-or-restart ssh
      return 0
    fi
    if ! run sshd -t; then
      rm -f "$dropin"
      die "sshd -t rejected the configuration; the drop-in was removed again"
    fi
    gaps="$(sshd_effective_gaps)"
    if [[ -n $gaps ]]; then
      rm -f "$dropin"
      die "effective sshd config is not hardened (sshd -T lacks: $(tr '\n' ',' <<<"$gaps")); the drop-in was removed again"
    fi
    run systemctl try-reload-or-restart ssh
    warn "SSH hardened. KEEP THIS SESSION OPEN and open a second SSH session as $TRADING_USER with your key before closing it."
  else
    gaps="$(sshd_effective_gaps)"
    if [[ -n $gaps ]]; then
      if [[ $DRY_RUN == 1 ]]; then
        warn "drop-in is present but sshd -T lacks: $(tr '\n' ',' <<<"$gaps")"
      else
        die "drop-in is present but the effective sshd config is not hardened (sshd -T lacks: $(tr '\n' ',' <<<"$gaps")); another file wins"
      fi
    fi
  fi
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
  PATH="$PATH:/usr/sbin:/sbin"
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
