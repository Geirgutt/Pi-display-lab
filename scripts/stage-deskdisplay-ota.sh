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
OTA_PROGRESS="$OTA_FILE.progress"
OTA_RESULT="$OTA_FILE.result"

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
  if [[ -n "$SSH_USER" && ${#WORKERS[@]} -gt 0 ]]; then
    echo "Ingen worker var tilgjengelig for firmwarebygging." >&2
    echo "Controlleren brukes ikke som treg fallback. Vent til en worker er ledig og prøv igjen." >&2
    exit 1
  fi
  echo "Ingen workers er konfigurert; bygger firmware lokalt." >&2
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
rm -f -- "$OTA_PROGRESS" "$OTA_RESULT"
echo "OTA-firmware er lagt i $OTA_FILE."
echo "Installerer DeskDisplay-gatewayen nå som OTA-firmwaren ligger klar ..."
# Keep the currently compatible gateway running while a worker builds. The new
# binary starts only after the image exists, so its first display session can
# offer OTA before sending any newly introduced telemetry frame.
bash scripts/install-deskdisplay-service.sh

OTA_TIMEOUT="${PI_DISPLAY_OTA_TIMEOUT:-900}"
if ! [[ "$OTA_TIMEOUT" =~ ^[1-9][0-9]*$ ]]; then
  echo "PI_DISPLAY_OTA_TIMEOUT må være et positivt antall sekunder." >&2
  exit 2
fi

progress_bar() {
  local percent="$1"
  local label="$2"
  local width=30
  local filled=$((percent * width / 100))
  local empty=$((width - filled))
  local left right
  left="$(printf '%*s' "$filled" '' | tr ' ' '#')"
  right="$(printf '%*s' "$empty" '' | tr ' ' '.')"
  printf '\r[%s%s] %3d%% %s' "$left" "$right" "$percent" "$label"
}

echo "Venter på OTA-overføring, reboot og ny TLS-tilkobling (inntil $OTA_TIMEOUT sekunder) ..."
STARTED_AT=$SECONDS
LAST_TEXT=""
LAST_PLAIN_UPDATE=0
while (( SECONDS - STARTED_AT < OTA_TIMEOUT )); do
  if [[ -f "$OTA_RESULT" ]] && read -r result _ <"$OTA_RESULT" && [[ "$result" == "success" ]]; then
    [[ ! -t 1 ]] || printf '\n'
    echo "OTA fullført: displayet har mottatt firmware, startet på nytt og koblet til TLS igjen."
    exit 0
  fi
  if ! systemctl is-active --quiet deskdisplay-secure-peer.service; then
    [[ ! -t 1 ]] || printf '\n'
    echo "DeskDisplay-gatewayen stoppet under OTA." >&2
    sudo journalctl -u deskdisplay-secure-peer.service -n 30 --no-pager >&2 || true
    exit 1
  fi

  state="waiting"
  offset=0
  total=0
  if [[ -f "$OTA_PROGRESS" ]]; then
    read -r state offset total <"$OTA_PROGRESS" || true
  fi
  percent=0
  label="venter på displayet"
  if [[ "$total" =~ ^[1-9][0-9]*$ && "$offset" =~ ^[0-9]+$ ]]; then
    percent=$((offset * 100 / total))
    (( percent > 100 )) && percent=100
  fi
  case "$state" in
    offer) label="displayet forbereder OTA" ;;
    transfer) label="overfører firmware" ;;
    delivered) percent=100; label="venter på reboot/TLS" ;;
    failed) label="overføring feilet; gatewayen prøver igjen" ;;
  esac
  text="$percent% $label"
  if [[ -t 1 ]]; then
    progress_bar "$percent" "$label"
  elif [[ "$text" != "$LAST_TEXT" || $((SECONDS - LAST_PLAIN_UPDATE)) -ge 30 ]]; then
    echo "OTA: $text"
    LAST_TEXT="$text"
    LAST_PLAIN_UPDATE=$SECONDS
  fi
  sleep 1
done

[[ ! -t 1 ]] || printf '\n'
if [[ -f "$OTA_FILE" ]]; then
  echo "OTA ble ikke bekreftet innen $OTA_TIMEOUT sekunder. Firmwarefilen beholdes for ny retry." >&2
else
  echo "Firmwaren ble levert, men reboot og ny TLS-tilkobling ble ikke bekreftet innen $OTA_TIMEOUT sekunder." >&2
fi
sudo journalctl -u deskdisplay-secure-peer.service -n 30 --no-pager >&2 || true
exit 1
