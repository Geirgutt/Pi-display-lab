#!/usr/bin/env bash

set -Eeuo pipefail

SERVICE_NAME="pi-display-lab"
SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
CONFIG_FILE="$PROJECT_DIR/config.local.json"

if [[ $EUID -eq 0 ]]; then
  echo "Kjør oppdateringen som vanlig bruker, ikke som root."
  exit 1
fi

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

CLUSTER_ENABLED="false"
if [[ -f "$CONFIG_FILE" ]]; then
  CLUSTER_ENABLED="$(python3 scripts/config-value.py cluster_enabled --config "$CONFIG_FILE")"
fi

echo "Kontrollerer lokal sudo-tilgang før Git endres ..."
if ! sudo -v; then
  echo "Oppdateringen trenger vanlig sudo-tilgang for å restarte tjenester."
  exit 1
fi

echo "Henter siste versjon av $BRANCH med fast-forward-only ..."
git fetch origin "$BRANCH"
git merge --ff-only "origin/$BRANCH"
REVISION="$(git rev-parse HEAD)"

if [[ "$CLUSTER_ENABLED" == "true" ]]; then
  if ! python3 scripts/config-value.py cluster_enabled --validate --config "$CONFIG_FILE" >/dev/null; then
    echo
    echo "Koden er oppdatert, men den lokale cluster-configen må migreres."
    echo "Kjør nå: python3 scripts/setup-cluster.py"
    exit 2
  fi
  echo "Oppdaterer controller og workers til eksakt commit $REVISION ..."
  bash scripts/install-cluster.sh
  exit 0
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
