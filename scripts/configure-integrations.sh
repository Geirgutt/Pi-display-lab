#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
RUN_USER="${SUDO_USER:-$(id -un)}"
RUN_GROUP="$(id -gn "$RUN_USER")"
CONFIG_DIR="/etc/pi-display-lab"
CONFIG_FILE="$CONFIG_DIR/integrations.json"

if [[ $EUID -eq 0 ]]; then
  echo "Kjør skriptet som vanlig controller-bruker, ikke som root."
  exit 1
fi

sudo install -d -o "$RUN_USER" -g "$RUN_GROUP" -m 0700 "$CONFIG_DIR"
"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/scripts/configure-integrations.py" \
  --config "$CONFIG_FILE" "$@"

if [[ -f "$CONFIG_FILE" ]]; then
  if ! sudo systemctl start pi-display-integrations.service; then
    echo "Kalenderne kunne ikke synkroniseres nå. Valgene er lagret, og timeren prøver igjen senere." >&2
  fi
  sudo systemctl restart pi-display-lab.service
fi
