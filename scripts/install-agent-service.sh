#!/usr/bin/env bash

set -Eeuo pipefail

SERVICE_NAME="pi-display-node-agent"
SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
RUN_USER="${SUDO_USER:-$(id -un)}"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
SERVER_URL="${1:-}"
NODE_NAME="${2:-$(hostname)}"
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"

if [[ $EUID -eq 0 && -z ${SUDO_USER:-} ]]; then
  echo "Kjør skriptet som vanlig bruker, ikke direkte som root."
  exit 1
fi

if [[ ! "$SERVER_URL" =~ ^https?://[^[:space:]]+$ ]]; then
  echo "Bruk: bash scripts/install-agent-service.sh http://HOVED-PI-IP:5000 [nodenavn]"
  exit 1
fi

if [[ ! "$NODE_NAME" =~ ^[A-Za-z0-9._-]{1,24}$ ]]; then
  echo "Nodenavn kan inneholde 1–24 bokstaver, tall, punktum, bindestrek eller understrek."
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Fant ikke $PYTHON_BIN"
  echo "Opprett miljøet først med: python3 -m venv .venv"
  exit 1
fi

TEMP_UNIT="$(mktemp)"
trap 'rm -f "$TEMP_UNIT"' EXIT

cat >"$TEMP_UNIT" <<EOF
[Unit]
Description=Pi Display Lab node agent
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_BIN $PROJECT_DIR/node_agent.py --server $SERVER_URL --name $NODE_NAME
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/etc/default/pi-display-lab-agent

[Install]
WantedBy=multi-user.target
EOF

echo "Installerer $UNIT_FILE for node $NODE_NAME ..."
sudo install -m 0644 "$TEMP_UNIT" "$UNIT_FILE"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME.service"
sudo systemctl restart "$SERVICE_NAME.service"

echo
sudo systemctl --no-pager --full status "$SERVICE_NAME.service"
