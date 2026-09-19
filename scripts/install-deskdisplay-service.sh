#!/usr/bin/env bash

set -Eeuo pipefail

SERVICE_NAME="deskdisplay-secure-peer"
SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
RUN_USER="${SUDO_USER:-$(id -un)}"
CONFIG_FILE="$PROJECT_DIR/config.local.json"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
RUNTIME_DIR="/usr/local/libexec/pi-display-lab"
BINARY="$RUNTIME_DIR/secure_peer"
OTA_DIR="/var/lib/pi-display-lab/deskdisplay"
OTA_FILE="$OTA_DIR/firmware.bin"
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"

if [[ $EUID -eq 0 && -z ${SUDO_USER:-} ]]; then
  echo "Kjør skriptet som vanlig bruker, ikke direkte som root."
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" || ! -f "$CONFIG_FILE" ]]; then
  echo "Mangler .venv eller config.local.json i $PROJECT_DIR"
  exit 1
fi

DESKDISPLAY_ENABLED="$("$PYTHON_BIN" "$PROJECT_DIR/scripts/config-value.py" deskdisplay_enabled --config "$CONFIG_FILE")"
if [[ "$DESKDISPLAY_ENABLED" != "true" ]]; then
  if sudo systemctl cat "$SERVICE_NAME.service" >/dev/null 2>&1; then
    echo "Deaktiverer DeskDisplay-gatewayen ..."
    sudo systemctl disable --now "$SERVICE_NAME.service"
  fi
  exit 0
fi

DESKDISPLAY_PORT="$("$PYTHON_BIN" "$PROJECT_DIR/scripts/config-value.py" deskdisplay_port --config "$CONFIG_FILE")"
APP_PORT="$("$PYTHON_BIN" "$PROJECT_DIR/scripts/config-value.py" app_port --config "$CONFIG_FILE")"
PSK_FILE="$("$PYTHON_BIN" "$PROJECT_DIR/scripts/config-value.py" deskdisplay_psk_file --config "$CONFIG_FILE")"
RUN_GROUP="$(id -gn "$RUN_USER")"
PSK_DIR="${PSK_FILE%/*}"
sudo install -d -o "$RUN_USER" -g "$RUN_GROUP" -m 0700 "$PSK_DIR"
if [[ ! -e "$PSK_FILE" ]]; then
  TEMP_PSK="$(mktemp)"
  trap 'rm -f "$TEMP_PSK"' EXIT
  umask 077
  echo "Genererer lokal DeskDisplay-PSK på controlleren ..."
  openssl rand -hex 32 >"$TEMP_PSK"
  sudo install -o "$RUN_USER" -g "$RUN_GROUP" -m 0600 "$TEMP_PSK" "$PSK_FILE"
  rm -f "$TEMP_PSK"
  trap - EXIT
fi
if ! sudo grep -Eq '^[[:space:]]*[0-9A-Fa-f]{64}[[:space:]]*$' "$PSK_FILE"; then
  echo "DeskDisplay-PSK finnes, men er ugyldig: $PSK_FILE. Den ble ikke overskrevet." >&2
  exit 1
fi
sudo chown "$RUN_USER:$RUN_GROUP" "$PSK_FILE"
sudo chmod 0600 "$PSK_FILE"

sudo install -d -o root -g root -m 0755 "$RUNTIME_DIR"
sudo install -d -o "$RUN_USER" -g "$RUN_GROUP" -m 0700 "$OTA_DIR"
sudo gcc -O2 -Wall -Wextra -I"$PROJECT_DIR/deskdisplay/src" \
  -o "$BINARY" "$PROJECT_DIR/deskdisplay/tools/secure_peer.c" -lssl -lcrypto
sudo chown root:root "$BINARY"
sudo chmod 0755 "$BINARY"

TEMP_UNIT="$(mktemp)"
trap 'rm -f "$TEMP_UNIT"' EXIT
cat >"$TEMP_UNIT" <<EOF
[Unit]
Description=Pi Display Lab DeskDisplay controller gateway
Wants=network-online.target
After=network-online.target pi-display-lab.service

[Service]
Type=simple
User=$RUN_USER
ExecStart=$BINARY --listen 0.0.0.0 --port $DESKDISPLAY_PORT --psk-file $PSK_FILE --state-host 127.0.0.1 --state-port $APP_PORT --state-path /api/deskdisplay/state --ota-file $OTA_FILE
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=$OTA_DIR
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
UMask=0077

[Install]
WantedBy=multi-user.target
EOF

sudo install -m 0644 "$TEMP_UNIT" "$UNIT_FILE"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME.service"
sudo systemctl restart "$SERVICE_NAME.service"
sudo systemctl --no-pager --full status "$SERVICE_NAME.service"
