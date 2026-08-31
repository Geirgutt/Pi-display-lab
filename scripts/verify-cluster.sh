#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
CONFIG_FILE="$PROJECT_DIR/config.local.json"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

if [[ ! -x "$PYTHON_BIN" || ! -f "$CONFIG_FILE" ]]; then
  echo "Mangler .venv eller config.local.json"
  exit 1
fi

cd "$PROJECT_DIR"

APP_PORT="$($PYTHON_BIN scripts/config-value.py app_port --config "$CONFIG_FILE")"
COORDINATOR_PORT="$($PYTHON_BIN scripts/config-value.py coordinator_port --config "$CONFIG_FILE")"

echo "Kontrollerer controller-tjenester ..."
systemctl is-active --quiet pi-display-lab.service
systemctl is-active --quiet cluster-coordinator.service

echo "Kontrollerer coordinator API ..."
curl --fail --silent --show-error "http://127.0.0.1:$COORDINATOR_PORT/health" >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:$COORDINATOR_PORT/status" >/dev/null

echo "Kontrollerer Pi Display Lab og cluster API ..."
curl --fail --silent --show-error "http://127.0.0.1:$APP_PORT/api/health" >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:$APP_PORT/api/cluster-jobs" >/dev/null

"$PYTHON_BIN" scripts/prepare-ansible.py "$CONFIG_FILE" "$TEMP_DIR"
if grep -q "ansible_user=" "$TEMP_DIR/inventory.ini"; then
  echo "Kontrollerer SSH og worker-tjenester ..."
  ansible all -i "$TEMP_DIR/inventory.ini" -m ansible.builtin.ping
  ansible all -i "$TEMP_DIR/inventory.ini" -b -m ansible.builtin.command -a "systemctl is-active cluster-worker.service"
  ansible all -i "$TEMP_DIR/inventory.ini" -b -m ansible.builtin.command -a "systemctl is-active pi-display-node-agent.service"
fi

echo "Alt ser bra ut: controller, coordinator, dashboard og workers svarer."
