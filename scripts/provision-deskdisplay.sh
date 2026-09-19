#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
CONFIG_FILE="$PROJECT_DIR/config.local.json"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
DISPLAY_PORT=""
WIFI_SSID=""
FLASH=true

usage() {
  cat <<'EOF'
Bruk: scripts/provision-deskdisplay.sh --port SERIAL_PORT [--wifi-ssid SSID] [--no-flash]

Flasher den sikre firmwarevarianten og legger lokal Wi-Fi/PSK/controller-
konfigurasjon i displayets NVS. PSK-en skrives aldri til terminalen eller repoet.
--no-flash brukes når secure-firmware allerede ligger på displayet.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port|--display-port)
      [[ $# -ge 2 ]] || { echo "$1 mangler verdi" >&2; exit 2; }
      DISPLAY_PORT="$2"
      shift 2
      ;;
    --wifi-ssid)
      [[ $# -ge 2 ]] || { echo "--wifi-ssid mangler verdi" >&2; exit 2; }
      WIFI_SSID="$2"
      shift 2
      ;;
    --no-flash)
      FLASH=false
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Ukjent valg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ $EUID -eq 0 ]]; then
  echo "Kjør display-provisjoneringen som vanlig bruker, ikke direkte som root." >&2
  exit 1
fi
if [[ -z "$DISPLAY_PORT" || ! -e "$DISPLAY_PORT" ]]; then
  echo "Mangler tilgjengelig display-port. Bruk --port /dev/serial/by-id/..." >&2
  exit 1
fi
if [[ ! -f "$CONFIG_FILE" || ! -x "$PYTHON_BIN" ]]; then
  echo "Mangler config.local.json eller .venv i $PROJECT_DIR" >&2
  exit 1
fi

DESKDISPLAY_ENABLED="$("$PYTHON_BIN" "$PROJECT_DIR/scripts/config-value.py" deskdisplay_enabled --config "$CONFIG_FILE")"
[[ "$DESKDISPLAY_ENABLED" == "true" ]] || {
  echo "deskdisplay.enabled må være true i config.local.json." >&2
  exit 1
}
CONTROLLER_HOST="$("$PYTHON_BIN" "$PROJECT_DIR/scripts/config-value.py" controller_host --config "$CONFIG_FILE")"
DESKDISPLAY_PORT_NUMBER="$("$PYTHON_BIN" "$PROJECT_DIR/scripts/config-value.py" deskdisplay_port --config "$CONFIG_FILE")"
PSK_FILE="$("$PYTHON_BIN" "$PROJECT_DIR/scripts/config-value.py" deskdisplay_psk_file --config "$CONFIG_FILE")"

if [[ ! -f "$PSK_FILE" ]] || ! grep -Eq '^[[:space:]]*[0-9A-Fa-f]{64}[[:space:]]*$' "$PSK_FILE"; then
  echo "Mangler gyldig lokal DeskDisplay-PSK: $PSK_FILE" >&2
  echo "Kjør først scripts/install-cluster.sh slik at PSK-en genereres på controlleren." >&2
  exit 1
fi
PSK="$(tr -d '[:space:]' <"$PSK_FILE")"

if [[ "$CONTROLLER_HOST" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
  CONTROLLER_IP="$CONTROLLER_HOST"
else
  CONTROLLER_IP="$(getent ahostsv4 "$CONTROLLER_HOST" | awk 'NR == 1 {print $1}')"
fi
if [[ ! "$CONTROLLER_IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
  echo "Fant ingen IPv4-adresse for controller_host: $CONTROLLER_HOST" >&2
  exit 1
fi

if [[ -z "$WIFI_SSID" && -t 0 && -r /dev/tty ]]; then
  read -r -p "Wi-Fi-SSID (tomt beholder lagrede credentials): " WIFI_SSID </dev/tty
  if [[ -n "$WIFI_SSID" ]]; then
    read -r -s -p "Wi-Fi-passord (skjult): " WIFI_PASSWORD </dev/tty
    printf '\n' >/dev/tty
  fi
elif [[ -n "$WIFI_SSID" ]]; then
  read -r -s -p "Wi-Fi-passord (skjult): " WIFI_PASSWORD </dev/tty
  printf '\n' >/dev/tty
else
  WIFI_PASSWORD=""
fi

if [[ "$FLASH" == "true" ]]; then
  PIO_BIN="$(command -v pio || true)"
  if [[ -z "$PIO_BIN" ]]; then
    DISPLAY_VENV="$PROJECT_DIR/.display-venv"
    if [[ ! -x "$DISPLAY_VENV/bin/python" ]]; then
      echo "Oppretter lokalt PlatformIO-miljø ..."
      python3 -m venv "$DISPLAY_VENV"
    fi
    echo "Installerer PlatformIO lokalt i prosjektmiljøet ..."
    "$DISPLAY_VENV/bin/python" -m pip install --disable-pip-version-check platformio
    PIO_BIN="$DISPLAY_VENV/bin/pio"
  fi
  echo "Bygger og flasher secure-firmware til $DISPLAY_PORT ..."
  (cd "$PROJECT_DIR/deskdisplay" && "$PIO_BIN" run -e guition-4848s040-secure)
  (cd "$PROJECT_DIR/deskdisplay" && "$PIO_BIN" run -e guition-4848s040-secure -t upload --upload-port "$DISPLAY_PORT")
  # Give the ESP32 time to reboot before opening its console.
  sleep 3
fi

stty -F "$DISPLAY_PORT" 115200 cs8 -cstopb -parenb -ixon -ixoff -icanon min 0 time 5
exec 3<>"$DISPLAY_PORT"

send_command() {
  printf '%s\n' "$1" >&3
  sleep 1
}

# The serial console does not echo the PSK. Do not enable shell tracing here.
if [[ -n "$WIFI_SSID" ]]; then
  send_command $'wifi '"$WIFI_SSID"$'\t'"$WIFI_PASSWORD"
fi
send_command "secure key $PSK"
send_command "secure peer $CONTROLLER_IP $DESKDISPLAY_PORT_NUMBER"
send_command "w"
send_command "secure start"
send_command "secure status"

STATUS_OUTPUT=""
while IFS= read -r -t 0.2 line <&3; do
  STATUS_OUTPUT+="$line"$'\n'
done
exec 3>&-
unset PSK WIFI_PASSWORD

if ! grep -q "Secure: " <<<"$STATUS_OUTPUT"; then
  echo "Displayet svarte ikke med secure status. Kontroller seriell port og firmware." >&2
  exit 1
fi
printf '%s' "$STATUS_OUTPUT"
echo "DeskDisplay er provisjonert mot $CONTROLLER_IP:$DESKDISPLAY_PORT_NUMBER."
