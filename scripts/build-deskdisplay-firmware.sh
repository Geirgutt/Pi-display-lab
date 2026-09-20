#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
BUILD_DIR="$PROJECT_DIR/deskdisplay/.pio/build/guition-4848s040-secure"

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

RUN_ARGS=(run -e guition-4848s040-secure)
if [[ -n ${PI_DISPLAY_BUILD_JOBS:-} ]]; then
  [[ "$PI_DISPLAY_BUILD_JOBS" =~ ^[1-9][0-9]*$ ]] || {
    echo "PI_DISPLAY_BUILD_JOBS må være et positivt heltall." >&2
    exit 2
  }
  RUN_ARGS+=(--jobs "$PI_DISPLAY_BUILD_JOBS")
fi

echo "Bygger DeskDisplay-firmware på $(getconf _NPROCESSORS_ONLN) CPU-kjerner ..."
(cd "$PROJECT_DIR/deskdisplay" && "$PIO_BIN" "${RUN_ARGS[@]}")

if [[ ! -s "$BUILD_DIR/firmware.bin" ]]; then
  echo "Fant ikke ferdig firmware: $BUILD_DIR/firmware.bin" >&2
  exit 1
fi

echo "DeskDisplay-firmware er ferdig: $BUILD_DIR/firmware.bin"
