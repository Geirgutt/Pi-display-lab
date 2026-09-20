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
BUILD_RELATIVE="deskdisplay/.pio/build/guition-4848s040-secure/firmware.bin"
OTA_FILE="/var/lib/pi-display-lab/deskdisplay/firmware.bin"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Mangler config.local.json i $PROJECT_DIR" >&2
  exit 1
fi

cd "$PROJECT_DIR"
REVISION="$(git rev-parse HEAD)"
[[ "$REVISION" =~ ^[0-9a-f]{40}$ ]] || { echo "Ugyldig Git-revisjon: $REVISION" >&2; exit 1; }
SSH_USER="$(python3 scripts/config-value.py ssh_user --config "$CONFIG_FILE")"
SSH_IDENTITY="$(python3 scripts/config-value.py ssh_identity_file --config "$CONFIG_FILE")"
mapfile -t CONFIGURED_WORKERS < <(python3 scripts/config-value.py worker_hosts --config "$CONFIG_FILE")
WORKERS=()
for host in "${CONFIGURED_WORKERS[@]}"; do
  [[ -z "$host" ]] || WORKERS+=("$host")
done

TEMP_BUILD="$(mktemp)"
TEMP_OTA=""
cleanup() {
  rm -f "$TEMP_BUILD"
  [[ -z "$TEMP_OTA" ]] || rm -f "$TEMP_OTA"
}
trap cleanup EXIT
REMOTE_BUILT=false
if [[ -n "$SSH_USER" && ${#WORKERS[@]} -gt 0 ]]; then
  SSH_OPTIONS=(-T -o StrictHostKeyChecking=yes -o ConnectTimeout=8 -o LogLevel=ERROR
    -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o BatchMode=yes)
  SCP_OPTIONS=(-o StrictHostKeyChecking=yes -o ConnectTimeout=8 -o LogLevel=ERROR
    -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o BatchMode=yes)
  if [[ -n "$SSH_IDENTITY" ]]; then
    SSH_OPTIONS+=(-i "$SSH_IDENTITY" -o IdentitiesOnly=yes)
    SCP_OPTIONS+=(-i "$SSH_IDENTITY" -o IdentitiesOnly=yes)
  fi
  REMOTE_COMMAND="cd \"\$HOME/Pi-display-lab\" && git fetch --quiet origin && git checkout --detach --quiet $REVISION && bash scripts/build-deskdisplay-firmware.sh"
  for BUILD_HOST in "${WORKERS[@]}"; do
    echo "Kontrollerer om worker $BUILD_HOST er ledig ..."
    set +e
    LOAD_INFO="$(ssh "${SSH_OPTIONS[@]}" "$SSH_USER@$BUILD_HOST" \
      "awk '{print \$1}' /proc/loadavg; getconf _NPROCESSORS_ONLN")"
    PROBE_RESULT=$?
    set -e
    if [[ $PROBE_RESULT -eq 255 ]]; then
      echo "$BUILD_HOST svarte ikke over SSH; prøver neste worker." >&2
      continue
    fi
    if [[ $PROBE_RESULT -ne 0 ]]; then
      echo "Kunne ikke kontrollere kapasiteten på $BUILD_HOST; prøver neste worker." >&2
      continue
    fi
    LOAD_ONE="$(sed -n '1p' <<<"$LOAD_INFO")"
    CORE_COUNT="$(sed -n '2p' <<<"$LOAD_INFO")"
    if ! [[ "$LOAD_ONE" =~ ^[0-9]+([.][0-9]+)?$ && "$CORE_COUNT" =~ ^[1-9][0-9]*$ ]]; then
      echo "$BUILD_HOST ga ugyldig lastinformasjon; prøver neste worker." >&2
      continue
    fi
    if awk -v load="$LOAD_ONE" -v cores="$CORE_COUNT" \
      'BEGIN { exit !(load >= cores * 0.75) }'; then
      echo "$BUILD_HOST er opptatt (load $LOAD_ONE på $CORE_COUNT kjerner); prøver neste worker."
      continue
    fi
    echo "Bygger DeskDisplay-firmware på worker $BUILD_HOST ..."
    set +e
    ssh "${SSH_OPTIONS[@]}" "$SSH_USER@$BUILD_HOST" "$REMOTE_COMMAND"
    BUILD_RESULT=$?
    set -e
    if [[ $BUILD_RESULT -eq 255 ]]; then
      echo "$BUILD_HOST svarte ikke over SSH; prøver neste worker." >&2
      continue
    fi
    if [[ $BUILD_RESULT -ne 0 ]]; then
      echo "Firmwarebyggingen feilet på $BUILD_HOST (kode $BUILD_RESULT)." >&2
      exit "$BUILD_RESULT"
    fi
    echo "Henter ferdig firmware fra $BUILD_HOST ..."
    scp "${SCP_OPTIONS[@]}" "$SSH_USER@$BUILD_HOST:Pi-display-lab/$BUILD_RELATIVE" "$TEMP_BUILD"
    REMOTE_BUILT=true
    break
  done
fi

if [[ "$REMOTE_BUILT" != "true" ]]; then
  echo "Ingen worker var tilgjengelig for bygging; bygger på controlleren (kan ta lang tid)." >&2
  bash scripts/build-deskdisplay-firmware.sh
  install -m 0600 "$BUILD_DIR/firmware.bin" "$TEMP_BUILD"
fi

if [[ ! -s "$TEMP_BUILD" ]]; then
  echo "Den ferdige firmwarefilen mangler eller er tom." >&2
  exit 1
fi

OTA_DIR="${OTA_FILE%/*}"
sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 0700 "$OTA_DIR"
TEMP_OTA="$(mktemp "$OTA_DIR/.firmware.bin.XXXXXX")"
install -m 0600 "$TEMP_BUILD" "$TEMP_OTA"
mv -f -- "$TEMP_OTA" "$OTA_FILE"
TEMP_OTA=""
echo "OTA-firmware er lagt i $OTA_FILE."
echo "Restarter DeskDisplay-gatewayen slik at displayet kan hente den ved neste tilkobling ..."
sudo systemctl restart deskdisplay-secure-peer.service
echo "OTA-firmware er klargjort. Displayet må ha OTA-støttet firmware fra USB minst én gang først."
