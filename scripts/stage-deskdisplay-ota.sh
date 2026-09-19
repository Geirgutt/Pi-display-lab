#!/usr/bin/env bash

set -Eeuo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Kjør OTA-klargjøringen som vanlig bruker, ikke direkte som root."
  exit 1
fi

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
CONFIG_FILE="$PROJECT_DIR/config.local.json"
BUILD_DIR="$PROJECT_DIR/deskdisplay/.pio/build/guition-4848s040-secure"
OTA_FILE="/var/lib/pi-display-lab/deskdisplay/firmware.bin"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Mangler config.local.json i $PROJECT_DIR" >&2
  exit 1
fi

cd "$PROJECT_DIR"
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

echo "Bygger OTA-firmware for DeskDisplay ..."
(cd "$PROJECT_DIR/deskdisplay" && "$PIO_BIN" run -e guition-4848s040-secure)

if [[ ! -s "$BUILD_DIR/firmware.bin" ]]; then
  echo "Fant ikke ferdig firmware: $BUILD_DIR/firmware.bin" >&2
  exit 1
fi

OTA_DIR="${OTA_FILE%/*}"
sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 0700 "$OTA_DIR"
TEMP_OTA="$(mktemp "$OTA_DIR/.firmware.bin.XXXXXX")"
trap 'rm -f "$TEMP_OTA"' EXIT
install -m 0600 "$BUILD_DIR/firmware.bin" "$TEMP_OTA"
mv -f -- "$TEMP_OTA" "$OTA_FILE"
trap - EXIT
echo "OTA-firmware er lagt i $OTA_FILE."
echo "Restarter DeskDisplay-gatewayen slik at displayet kan hente den ved neste tilkobling ..."
sudo systemctl restart deskdisplay-secure-peer.service
echo "OTA-firmware er klargjort. Displayet må ha OTA-støttet firmware fra USB minst én gang først."
