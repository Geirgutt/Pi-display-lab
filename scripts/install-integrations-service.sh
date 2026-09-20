#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
RUN_USER="${SUDO_USER:-$(id -un)}"
RUN_GROUP="$(id -gn "$RUN_USER")"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
CONFIG_DIR="/etc/pi-display-lab"
CACHE_DIR="/var/lib/pi-display-lab/integrations"
SERVICE_FILE="/etc/systemd/system/pi-display-integrations.service"
TIMER_FILE="/etc/systemd/system/pi-display-integrations.timer"

if [[ $EUID -eq 0 ]]; then
  echo "Kjør skriptet som vanlig controller-bruker, ikke som root."
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Mangler controllerens Python-miljø: $PYTHON_BIN" >&2
  exit 1
fi

echo "Installerer kalenderstøtte i controllerens Python-miljø ..."
"$PYTHON_BIN" -m pip install --disable-pip-version-check -r "$PROJECT_DIR/requirements-integrations.txt"

sudo install -d -o "$RUN_USER" -g "$RUN_GROUP" -m 0700 "$CONFIG_DIR" "$CACHE_DIR"
TEMP_SERVICE="$(mktemp)"
TEMP_TIMER="$(mktemp)"
trap 'rm -f "$TEMP_SERVICE" "$TEMP_TIMER"' EXIT

cat >"$TEMP_SERVICE" <<EOF
[Unit]
Description=Pi Display Lab calendar synchronization
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_BIN $PROJECT_DIR/scripts/sync-integrations.py
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=read-only
ProtectSystem=strict
ReadOnlyPaths=$CONFIG_DIR
ReadWritePaths=$CACHE_DIR
UMask=0077
EOF

cat >"$TEMP_TIMER" <<EOF
[Unit]
Description=Refresh Pi Display Lab calendars periodically

[Timer]
OnBootSec=90s
OnUnitActiveSec=15min
RandomizedDelaySec=30s
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo install -m 0644 "$TEMP_SERVICE" "$SERVICE_FILE"
sudo install -m 0644 "$TEMP_TIMER" "$TIMER_FILE"
sudo systemctl daemon-reload
sudo systemctl enable --now pi-display-integrations.timer
