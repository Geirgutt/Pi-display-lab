#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
CONFIG_FILE="$PROJECT_DIR/config.local.json"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
TEMP_DIR="$(mktemp -d)"
chmod 0700 "$TEMP_DIR"
trap 'rm -rf "$TEMP_DIR"' EXIT

if [[ ! -x "$PYTHON_BIN" || ! -f "$CONFIG_FILE" ]]; then
  echo "Mangler .venv eller config.local.json"
  exit 1
fi

cd "$PROJECT_DIR"
REVISION="$(git rev-parse HEAD)"
"$PYTHON_BIN" scripts/prepare-ansible.py \
  "$CONFIG_FILE" \
  "$TEMP_DIR" \
  --revision "$REVISION"

echo "Kontrollerer controller-tjenester ..."
systemctl is-active --quiet pi-display-lab.service
systemctl is-active --quiet cluster-coordinator.service

echo "Kontrollerer app, coordinator og autentisert status ..."
"$PYTHON_BIN" scripts/verify-controller-api.py "$CONFIG_FILE"

echo "Kontrollerer SSH til workerne ..."
ansible all -i "$TEMP_DIR/inventory.ini" -m ansible.builtin.ping

echo "Kontrollerer worker-tjenester uten sudo ..."
ansible all \
  -i "$TEMP_DIR/inventory.ini" \
  -m ansible.builtin.command \
  -a "systemctl is-active cluster-worker.service"
ansible all \
  -i "$TEMP_DIR/inventory.ini" \
  -m ansible.builtin.command \
  -a "systemctl is-active pi-display-node-agent.service"

echo "Alt ser bra ut: controller, coordinator-auth, dashboard og workers svarer."
