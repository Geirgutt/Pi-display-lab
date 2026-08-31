#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
CONFIG_FILE="$PROJECT_DIR/config.local.json"
VENV_DIR="$PROJECT_DIR/.venv"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

if [[ $EUID -eq 0 ]]; then
  echo "Kjør skriptet som vanlig bruker med sudo-tilgang, ikke som root."
  exit 1
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Mangler config.local.json. Start med: cp config.example.json config.local.json"
  exit 1
fi

cd "$PROJECT_DIR"
echo "Installerer controller-avhengigheter ..."
sudo apt-get update
sudo apt-get install -y ansible curl git python3 python3-venv

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check -r requirements.txt
"$VENV_DIR/bin/python" scripts/prepare-ansible.py "$CONFIG_FILE" "$TEMP_DIR"

echo "Installerer controller-tjenester ..."
bash scripts/install-service.sh
bash scripts/install-coordinator-service.sh

if grep -q "ansible_user=" "$TEMP_DIR/inventory.ini"; then
  echo "Installerer workerne med Ansible ..."
  ansible-playbook \
    -i "$TEMP_DIR/inventory.ini" \
    ansible/install-workers.yml \
    --extra-vars "@$TEMP_DIR/vars.json"
else
  echo "Ingen worker_hosts er konfigurert; hopper over worker-installasjon."
fi

echo
bash scripts/verify-cluster.sh
