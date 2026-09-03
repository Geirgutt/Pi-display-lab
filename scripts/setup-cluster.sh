#!/usr/bin/env bash
# Bootstrap before importing the Python wizard, including on a fresh Pi OS.
set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
if [[ $EUID -eq 0 ]]; then
  echo "Kjør oppsettet som vanlig bruker med sudo-tilgang, ikke som root."
  exit 1
fi
source "$PROJECT_DIR/scripts/platform.sh"
platform_detect
source "$PROJECT_DIR/scripts/sudo-session.sh"
trap 'sudo_session_stop' EXIT

platform_missing_packages
if [[ ${#MISSING[@]} -gt 0 || ! -x "$PROJECT_DIR/.ansible-venv/bin/ansible-playbook" ]]; then
  echo "Koordinatoren mangler: ${MISSING[*]}"
  echo "Ansible klargjøres i prosjektets eget Python-miljø."
  read -r -p "Installere disse verktøyene og fortsette oppsettet? [J/n] " ANSWER
  case "${ANSWER,,}" in
    ''|j|ja|y|yes) ;;
    *) echo "Oppsettet ble avbrutt."; exit 0 ;;
  esac
fi
echo "Kontrollerer sudo på koordinatoren ..."
sudo_session_start
platform_install_packages
platform_setup_ansible
cd "$PROJECT_DIR"
PI_DISPLAY_SETUP_READY=1 python3 scripts/setup-cluster.py
