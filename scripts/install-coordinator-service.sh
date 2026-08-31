#!/usr/bin/env bash

set -Eeuo pipefail

SERVICE_NAME="cluster-coordinator"
SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
RUN_USER="${SUDO_USER:-$(id -un)}"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"

if [[ $EUID -eq 0 && -z ${SUDO_USER:-} ]]; then
  echo "Kjør skriptet som vanlig bruker, ikke direkte som root."
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" || ! -f "$PROJECT_DIR/config.local.json" ]]; then
  echo "Mangler .venv eller config.local.json i $PROJECT_DIR"
  exit 1
fi

TEMP_UNIT="$(mktemp)"
trap 'rm -f "$TEMP_UNIT"' EXIT

cat >"$TEMP_UNIT" <<EOF
[Unit]
Description=Pi Display Lab cluster coordinator
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_BIN $PROJECT_DIR/cluster_coordinator.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo install -m 0644 "$TEMP_UNIT" "$UNIT_FILE"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME.service"
sudo systemctl restart "$SERVICE_NAME.service"
sudo systemctl --no-pager --full status "$SERVICE_NAME.service"
