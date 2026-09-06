#!/usr/bin/env bash
# Shared local dependency setup for Debian/Ubuntu/Pi OS and Fedora.

platform_detect() {
  if [[ ! -r /etc/os-release ]]; then
    echo "Kan ikke identifisere Linux-systemet." >&2
    return 1
  fi
  source /etc/os-release
  case "${ID:-}" in
    debian|ubuntu|raspbian) PLATFORM_FAMILY=debian ;;
    fedora) PLATFORM_FAMILY=fedora ;;
    *) echo "Ustøttet system: ${PRETTY_NAME:-ukjent}. Bruk Debian, Ubuntu, Raspberry Pi OS eller Fedora." >&2; return 1 ;;
  esac
  case "$(uname -m)" in
    x86_64|aarch64|armv7l|armv8l) ;;
    *) echo "Ustøttet prosessorarkitektur: $(uname -m)" >&2; return 1 ;;
  esac
  command -v systemctl >/dev/null || { echo "Installasjonen krever systemd." >&2; return 1; }
  if [[ "$PLATFORM_FAMILY" == debian ]]; then
    PLATFORM_PACKAGES=(git openssh-client openssl python3 python3-venv python3-packaging python3-cryptography python3-yaml python3-jinja2 sshpass curl)
  else
    PLATFORM_PACKAGES=(git openssh-clients openssl python3 python3-pip python3-packaging python3-cryptography python3-pyyaml python3-jinja2 sshpass curl)
  fi
  echo "Oppdaget ${PRETTY_NAME:-$ID}, $(uname -m)."
}

platform_missing_packages() {
  MISSING=()
  local package
  for package in "${PLATFORM_PACKAGES[@]}"; do
    if [[ "$PLATFORM_FAMILY" == debian ]]; then
      [[ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)" == 'install ok installed' ]] || MISSING+=("$package")
    else
      rpm -q "$package" >/dev/null 2>&1 || MISSING+=("$package")
    fi
  done
}

platform_install_packages() {
  [[ ${#MISSING[@]} -gt 0 ]] || return 0
  if [[ "$PLATFORM_FAMILY" == debian ]]; then
    sudo env DEBIAN_FRONTEND=noninteractive apt-get update
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -o Dpkg::Options::=--force-confold "${MISSING[@]}"
  else
    sudo dnf --refresh -y install "${MISSING[@]}"
  fi
}

platform_setup_ansible() {
  if ! python3 -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 14) else 1)'; then
    echo "Koordinatoren trenger Python 3.11–3.14 (for eksempel Debian 12/13 eller Ubuntu 24.04)." >&2
    return 1
  fi
  if [[ ! -x "$PROJECT_DIR/.ansible-venv/bin/python" ]]; then
    python3 -m venv --system-site-packages "$PROJECT_DIR/.ansible-venv"
  fi
  "$PROJECT_DIR/.ansible-venv/bin/python" -m pip install --upgrade --disable-pip-version-check -r "$PROJECT_DIR/requirements-ansible.txt"
  "$PROJECT_DIR/.ansible-venv/bin/python" "$PROJECT_DIR/ansible_environment.py"
  export PATH="$PROJECT_DIR/.ansible-venv/bin:$PATH"
}
