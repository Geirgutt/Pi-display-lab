#!/usr/bin/env bash

set -Eeuo pipefail

SERVICE_NAME="pi-display-lab"
SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
CONFIG_FILE="$PROJECT_DIR/config.local.json"
DISPLAY_MODE=""
DISPLAY_ONLY=false
FORCE_FULL=false
ORIGINAL_ARGS=("$@")

if [[ $EUID -eq 0 ]]; then
  echo "Kjør oppdateringen som vanlig bruker, ikke som root."
  exit 1
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --display-ota)
      DISPLAY_MODE="ota"
      shift
      ;;
    --display-only)
      DISPLAY_ONLY=true
      shift
      ;;
    --full)
      FORCE_FULL=true
      shift
      ;;
    *)
      echo "Ukjent valg: $1" >&2
      exit 2
      ;;
  esac
done

cd "$PROJECT_DIR"

if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  echo "Oppdatering avbrutt: prosjektmappen har lokale endringer."
  echo "Kontroller dem med: git status"
  exit 1
fi

BRANCH="$(git branch --show-current)"
if [[ -z "$BRANCH" ]]; then
  echo "Oppdatering avbrutt: Git står ikke på en navngitt branch."
  exit 1
fi

source "$PROJECT_DIR/scripts/sudo-session.sh"
trap 'sudo_session_stop' EXIT

PREVIOUS_REVISION="${PI_DISPLAY_UPDATE_PREVIOUS_REVISION:-$(git rev-parse HEAD)}"

echo "Kontrollerer lokal sudo-tilgang før Git endres ..."
if ! sudo_session_start; then
  echo "Oppdateringen trenger vanlig sudo-tilgang for å restarte tjenester."
  exit 1
fi

echo "Henter siste versjon av $BRANCH med fast-forward-only ..."
git fetch origin "$BRANCH"
git merge --ff-only "origin/$BRANCH"
REVISION="$(git rev-parse HEAD)"
echo "Lokal checkout er nå commit $REVISION."

# Bash may have buffered the old script before git merge. Re-exec once when
# update.sh itself changed so the fetched version controls classification.
if [[ "${PI_DISPLAY_UPDATE_REEXEC:-}" != "$REVISION" ]] \
    && ! git diff --quiet "$PREVIOUS_REVISION" "$REVISION" -- scripts/update.sh; then
  echo "Oppdateringsskriptet er endret; starter den nye versjonen ..."
  sudo_session_stop
  trap - EXIT
  export PI_DISPLAY_UPDATE_PREVIOUS_REVISION="$PREVIOUS_REVISION"
  export PI_DISPLAY_UPDATE_REEXEC="$REVISION"
  exec bash "$PROJECT_DIR/scripts/update.sh" "${ORIGINAL_ARGS[@]}"
fi

# Read this only after the fast-forward. The fetched version owns the update
# flow, including the first-time DeskDisplay selection prompt.
CLUSTER_ENABLED="false"
DISPLAY_OTA_READY="false"
if [[ -f "$CONFIG_FILE" ]]; then
  CLUSTER_ENABLED="$(python3 scripts/config-value.py cluster_enabled --config "$CONFIG_FILE")"
  DISPLAY_OTA_READY="$(python3 scripts/config-value.py deskdisplay_ota_ready --config "$CONFIG_FILE")"
fi

prompt_yes_no() {
  local answer=""
  [[ -r /dev/tty ]] || return 1
  read -r -p "$1 [j/N] " answer </dev/tty || return 1
  case "${answer,,}" in
    j|ja|y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

UPDATE_MODE="full"
DISPLAY_CHANGED=false
if [[ "$CLUSTER_ENABLED" == "true" ]]; then
  read -r UPDATE_MODE DISPLAY_CHANGED < <(
    python3 scripts/classify-update.py "$PREVIOUS_REVISION" "$REVISION"
  )
  if [[ "$FORCE_FULL" == "true" ]]; then
    UPDATE_MODE="full"
    echo "Full oppdatering er eksplisitt valgt."
  elif [[ "$UPDATE_MODE" == "ask" ]]; then
    echo "Disse endringene er ikke klassifisert som en kjent hurtigoppdatering:"
    git diff --name-only "$PREVIOUS_REVISION" "$REVISION" | sed 's/^/  - /'
    if prompt_yes_no "Kjøre en full og grundig oppdatering?"; then
      UPDATE_MODE="full"
    else
      echo "Oppdateringen stoppet før controller eller workers ble endret."
      exit 2
    fi
  fi

  if [[ "$DISPLAY_ONLY" == "true" ]]; then
    UPDATE_MODE="display"
    DISPLAY_CHANGED=true
  elif [[ "$UPDATE_MODE" == "display" ]]; then
    DISPLAY_ONLY=true
    echo "Endringene gjelder bare DeskDisplay. Hopper over vanlig cluster-oppdatering."
  elif [[ "$UPDATE_MODE" == "none" && -n "$DISPLAY_MODE" ]]; then
    DISPLAY_ONLY=true
    DISPLAY_CHANGED=true
  elif [[ "$UPDATE_MODE" == "none" ]]; then
    echo "Ingen nye commits å installere. Bruk --full for reparasjon/reinstallasjon."
    exit 0
  elif [[ "$UPDATE_MODE" == "quick" ]]; then
    if ! python3 scripts/check-cluster-pki.py "$CONFIG_FILE"; then
      echo "Hurtigoppdatering er ikke forsvarlig før PKI er kontrollert. Bytter til full oppdatering."
      UPDATE_MODE="full"
    else
      echo "Trygg runtime-endring oppdaget: bruker hurtigoppdatering uten pakke-, PKI- eller credential-distribusjon."
    fi
  else
    echo "Installasjons-, dependency-, konfigurasjons- eller sikkerhetsendring oppdaget: bruker full oppdatering."
  fi
fi

if [[ "$CLUSTER_ENABLED" == "true" && "$DISPLAY_ONLY" != "true" \
      && "$DISPLAY_CHANGED" == "true" && -z "$DISPLAY_MODE" ]]; then
  if prompt_yes_no "Skal DeskDisplay oppdateres nå?"; then
    if prompt_yes_no "Er DeskDisplay tilkoblet clusteret med USB-kabel nå?"; then
      DISPLAY_MODE="cable"
    else
      DISPLAY_MODE="ota"
      echo "OTA valgt. Displayet må allerede ha OTA-støttet firmware og være på Wi-Fi."
    fi
  else
    DISPLAY_MODE="none"
  fi
fi

if [[ "$CLUSTER_ENABLED" == "true" && "$DISPLAY_ONLY" != "true" && -z "$DISPLAY_MODE" ]]; then
  DISPLAY_MODE="none"
fi

if [[ "$DISPLAY_MODE" == "ota" && "$DISPLAY_OTA_READY" != "true" ]]; then
  echo "OTA for DeskDisplay er ikke klargjort ennå. Koble displayet til en Pi med USB-kabel og kjør oppdateringen på nytt." >&2
  echo "Oppdateringen stoppes før controller/workers endres." >&2
  exit 2
fi

if [[ "$CLUSTER_ENABLED" == "true" ]]; then
  if ! python3 scripts/config-value.py cluster_enabled --validate --config "$CONFIG_FILE" >/dev/null; then
    echo
    echo "Koden er oppdatert, men den lokale cluster-configen må migreres."
    echo "Kjør nå: python3 scripts/setup-cluster.py"
    exit 2
  fi
  if [[ "$DISPLAY_ONLY" == "true" ]]; then
    if [[ -z "$DISPLAY_MODE" ]]; then
      if prompt_yes_no "Er DeskDisplay tilkoblet clusteret med USB-kabel nå?"; then
        DISPLAY_MODE="cable"
      else
        DISPLAY_MODE="ota"
      fi
    fi
    if [[ "$DISPLAY_MODE" == "ota" && "$DISPLAY_OTA_READY" != "true" ]]; then
      echo "OTA for DeskDisplay er ikke klargjort ennå. Koble displayet til en Pi med USB-kabel først." >&2
      exit 2
    fi
    if [[ "$DISPLAY_MODE" == "ota" ]]; then
      echo "Oppdaterer kun DeskDisplay over OTA ..."
      bash scripts/install-deskdisplay-service.sh
      bash scripts/stage-deskdisplay-ota.sh
    else
      TEMP_DIR="$(mktemp -d)"
      chmod 0700 "$TEMP_DIR"
      trap 'rm -rf "$TEMP_DIR"; sudo_session_stop' EXIT
      echo "Oppdaterer kun DeskDisplay via USB ..."
      bash scripts/install-deskdisplay-service.sh
      python3 cluster_install.py "$CONFIG_FILE" "$TEMP_DIR" "$REVISION" \
        --display-mode cable --display-only
    fi
    exit 0
  fi
  if [[ "$UPDATE_MODE" == "quick" ]]; then
    echo "Hurtigoppdaterer controller og workers til eksakt commit $REVISION ..."
    bash scripts/install-cluster.sh --quick --display-mode "$DISPLAY_MODE"
  else
    echo "Fulloppdaterer controller og workers til eksakt commit $REVISION ..."
    bash scripts/install-cluster.sh --display-mode "$DISPLAY_MODE"
  fi
  if [[ "$DISPLAY_MODE" == "ota" ]]; then
    bash scripts/stage-deskdisplay-ota.sh
  fi
  exit 0
fi

if [[ "$DISPLAY_MODE" == "ota" ]]; then
  echo "--display-ota krever aktivert cluster og DeskDisplay-gateway." >&2
  exit 2
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Oppretter Python-miljø ..."
  python3 -m venv "$VENV_DIR"
fi

echo "Kontrollerer Python-pakkene ..."
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check -r requirements.txt

if ! systemctl cat "$SERVICE_NAME.service" >/dev/null 2>&1; then
  echo "Koden er oppdatert, men systemd-tjenesten er ikke installert."
  echo "Kjør: bash scripts/install-service.sh"
  exit 0
fi

echo "Starter Pi Display Lab på nytt ..."
sudo systemctl restart "$SERVICE_NAME.service"
if systemctl is-active --quiet "$SERVICE_NAME.service"; then
  echo "Oppdateringen er ferdig. $SERVICE_NAME kjører commit $REVISION."
else
  echo "Tjenesten startet ikke som forventet. Viser status:"
  systemctl --no-pager --full status "$SERVICE_NAME.service"
  exit 1
fi
