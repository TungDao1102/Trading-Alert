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
# shellcheck source=lib.sh
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
  validate_secrets_file "$SECRETS_FILE"
  if [[ -n $DEPLOY_KEY && ! -f $DEPLOY_KEY ]]; then
    die "deploy key is not a file: $DEPLOY_KEY"
  fi

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
  local -a port_list
  ports="$(effective_ssh_ports)"
  if [[ -z $ports ]]; then
    if [[ $DRY_RUN == 1 ]]; then
      ports="<ssh-port>"
    else
      die "lock-out guard: could not read the effective SSH port from 'sshd -T'; not touching the firewall"
    fi
  fi
  mapfile -t port_list <<<"$ports"
  status="$(ufw status verbose 2>/dev/null || true)"
  grep -q '^Status: active' <<<"$status" || ok=0
  grep -qi 'deny (incoming)' <<<"$status" || ok=0
  for port in "${port_list[@]}"; do
    grep -Eq "^${port}/tcp.*ALLOW" <<<"$status" || ok=0
  done
  if ((ok)); then
    log "ufw already active with default deny incoming and the SSH allow rule"
    return 0
  fi
  # Allow rules first: on an already active firewall, flipping the default to deny before the
  # SSH rule exists would drop new SSH connections (permanently if `ufw allow` then failed).
  for port in "${port_list[@]}"; do
    run ufw allow "${port}/tcp"
  done
  run ufw default deny incoming
  run ufw default allow outgoing
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

# clock_status: sets CLOCK_MSG. Returns 0 when chrony is synchronised and the system clock is
# within MAX_DRIFT_MS of NTP time, 1 when it is not (yet) synchronised, 2 when drift is too big.
# Parses the documented text format of `chronyc tracking`, never the undocumented CSV mode.
CLOCK_MSG=""
clock_status() {
  local out leap sys ms
  if ! out="$(chronyc tracking 2>/dev/null)"; then
    CLOCK_MSG="chronyc tracking failed (is chrony running?)"
    return 1
  fi
  leap="$(awk -F: '/^Leap status/ { gsub(/^[ \t]+|[ \t]+$/, "", $2); print $2; exit }' <<<"$out")"
  if [[ $leap != Normal ]]; then
    CLOCK_MSG="chrony is not synchronised (Leap status: ${leap:-unknown})"
    return 1
  fi
  sys="$(awk '/^System time/ { print $4; exit }' <<<"$out")"
  if [[ ! $sys =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    CLOCK_MSG="cannot parse the 'System time' line of chronyc tracking"
    return 1
  fi
  ms="$(awk -v s="$sys" 'BEGIN { printf "%.3f", s * 1000 }')"
  if awk -v m="$ms" -v b="$MAX_DRIFT_MS" 'BEGIN { exit !(m > b) }'; then
    CLOCK_MSG="clock drift $ms ms exceeds the $MAX_DRIFT_MS ms bound"
    return 2
  fi
  CLOCK_MSG="clock drift $ms ms (bound $MAX_DRIFT_MS ms)"
}

step_chrony() {
  local changed=0 rc=0 max_correction
  if ! pkg_installed chrony; then
    changed=1
  fi
  apt_install_missing chrony
  if systemctl is-enabled systemd-timesyncd >/dev/null 2>&1; then
    run systemctl disable --now systemd-timesyncd
  fi
  if ! systemctl is-enabled chrony >/dev/null 2>&1; then
    changed=1
    run systemctl enable --now chrony
  fi
  clock_status || rc=$?
  if ((rc != 0 || changed)); then
    max_correction="$(awk -v b="$MAX_DRIFT_MS" 'BEGIN { printf "%.3f", b / 1000 }')"
    if ! run chronyc waitsync 60 "$max_correction" 0 2; then
      die "chronyc waitsync did not report a synchronised clock within the bound"
    fi
    if [[ $DRY_RUN == 1 ]]; then
      printf '+ verify clock drift <= %s ms with chronyc tracking\n' "$MAX_DRIFT_MS"
      return 0
    fi
    rc=0
    clock_status || rc=$?
  fi
  ((rc == 0)) || die "$CLOCK_MSG"
  log "$CLOCK_MSG"
}

# Checkout runs as the trading user so the tree is owned by it; REF should be a tag or commit.
step_checkout() {
  local dir key_dst head target
  local -a gitcmd=(runuser -u "$TRADING_USER" --)
  dir="$(p "$INSTALL_DIR")"
  if [[ -n $DEPLOY_KEY ]]; then
    key_dst="$(p "$USER_HOME/.ssh/id_deploy")"
    if [[ ! -f $key_dst ]] || ! cmp -s "$DEPLOY_KEY" "$key_dst"; then
      run install -m 0600 -o "$TRADING_USER" -g "$TRADING_USER" "$DEPLOY_KEY" "$key_dst"
    fi
    gitcmd+=(env "GIT_SSH_COMMAND=ssh -i $USER_HOME/.ssh/id_deploy -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new")
  fi
  gitcmd+=(git)

  if [[ -d $dir/.git ]]; then
    head="$("${gitcmd[@]}" -C "$dir" rev-parse HEAD 2>/dev/null || true)"
    target="$("${gitcmd[@]}" -C "$dir" rev-parse --verify --quiet "${REPO_REF}^{commit}" 2>/dev/null || true)"
    if [[ -n $head && $head == "$target" ]]; then
      log "repository already at $REPO_REF"
      return 0
    fi
    run "${gitcmd[@]}" -C "$dir" fetch --tags origin
  else
    if [[ ! -d $dir ]]; then
      run install -d -o "$TRADING_USER" -g "$TRADING_USER" "$dir"
    fi
    run "${gitcmd[@]}" clone "$REPO_URL" "$dir"
  fi
  run "${gitcmd[@]}" -C "$dir" checkout --detach "$REPO_REF"
}

REQUIRED_ENV_KEYS=(POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB)

# validate_secrets_file FILE: required keys present and non-empty, no change_me placeholders.
# Reports key NAMES only; a value is never read into a message (OPS-06, T-13.1-21).
validate_secrets_file() {
  local file=$1 problems
  # Bash pattern match, not grep: Git-for-Windows grep strips the CR before matching.
  if [[ "$(<"$file")" == *$'\r'* ]]; then
    die "secrets file has CR (Windows) line endings; convert it to LF first: $file"
  fi
  problems="$(awk -v req="${REQUIRED_ENV_KEYS[*]}" '
    BEGIN { n = split(req, need, " "); sq = sprintf("%c", 39); dq = sprintf("%c", 34) }
    /^[ \t]*#/ || /^[ \t]*$/ { next }
    {
      line = $0
      sub(/^[ \t]*export[ \t]+/, "", line)
      i = index(line, "=")
      if (i == 0) next
      key = substr(line, 1, i - 1)
      gsub(/[ \t]/, "", key)
      val = substr(line, i + 1)
      sub(/^[ \t]+/, "", val)
      sub(/[ \t]+$/, "", val)
      first = substr(val, 1, 1)
      last = substr(val, length(val), 1)
      if (length(val) >= 2 && first == last && (first == sq || first == dq)) {
        val = substr(val, 2, length(val) - 2)
      }
      if (!(key in value)) order[++count] = key
      value[key] = val
    }
    END {
      for (k = 1; k <= n; k++) {
        if (!(need[k] in value) || value[need[k]] == "") print "missing or empty: " need[k]
      }
      for (k = 1; k <= count; k++) {
        if (tolower(value[order[k]]) ~ /change_me/) print "placeholder value: " order[k]
      }
    }' "$file")"
  if [[ -n $problems ]]; then
    # shellcheck disable=SC2001  # sed prefixes every line; parameter expansion cannot
    die "secrets file is not usable ($file):
$(sed 's/^/  /' <<<"$problems")"
  fi
}

# .env is installed with umask 077 and mode 0600 owned by the trading user (OPS-06).
step_env() {
  local dest mode
  dest="$(p "$INSTALL_DIR/.env")"
  if [[ -f $dest ]] && cmp -s "$SECRETS_FILE" "$dest"; then
    if ! posix_modes_supported || [[ "$(stat -c %a "$dest")" == 600 ]]; then
      log ".env already installed"
      return 0
    fi
  fi
  (
    umask 077
    run install -m 0600 -o "$TRADING_USER" -g "$TRADING_USER" "$SECRETS_FILE" "$dest"
  )
  if [[ $DRY_RUN != 1 ]] && posix_modes_supported; then
    mode="$(stat -c %a "$dest")"
    [[ $mode == 600 ]] || die ".env has mode $mode after install, expected 600"
  fi
}

print_checklist() {
  cat <<EOF

Operator checklist (none of this is automated):
  1. Binance API key: restrict it to this host's public IP (IP whitelist / IP allow list) and
     leave the withdrawal permission off; the key must have no withdrawal permission.
  2. Heartbeat: register an off-VPS heartbeat monitor so a silent host is noticed.
  3. Backup crypt passphrase: store it off the VPS; losing it makes every backup unrecoverable.
  4. SSH: before closing this session, open a second SSH session as $TRADING_USER with your key.
  5. Provider disk encryption: enable it (or confirm it is on) in the provider console.
  6. Backups: set the BACKUP_* variables in $INSTALL_DIR/.env as $TRADING_USER, and run
       $INSTALL_DIR/deploy/backup.sh --init-remote
     as $TRADING_USER. Root SSH login is now disabled and $TRADING_USER has no sudo, so install
     the timer as root from the provider console (or from this root session, before you close it;
     the install does not read .env):
       $INSTALL_DIR/deploy/backup.sh --install-timer
     The same applies to every later apt, ufw or systemctl change: reach root via the console.
  7. The docker group is root-equivalent: keep it to this one operator account. ufw does not
     control ports published by Docker; publish only 127.0.0.1 ports.
  8. Delete the copied secrets file from this host once .env is verified: $SECRETS_FILE
EOF
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
