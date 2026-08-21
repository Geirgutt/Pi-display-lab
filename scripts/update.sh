#!/usr/bin/env bash

set -Eeuo pipefail

SERVICE_NAME="pi-display-lab"
SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

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

echo "Henter siste versjon av $BRANCH ..."
git fetch origin "$BRANCH"
git merge --ff-only "origin/$BRANCH"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Oppretter Python-miljø ..."
  python3 -m venv "$VENV_DIR"
fi

echo "Kontrollerer Python-pakkene ..."
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check -r requirements.txt

if ! systemctl cat "$SERVICE_NAME.service" >/dev/null 2>&1; then
  echo
  echo "Koden er oppdatert, men systemd-tjenesten er ikke installert."
  echo "Kjør: bash scripts/install-service.sh"
  exit 0
fi

echo "Starter tjenesten på nytt ..."
sudo systemctl restart "$SERVICE_NAME.service"

if systemctl is-active --quiet "$SERVICE_NAME.service"; then
  echo "Oppdateringen er ferdig. $SERVICE_NAME kjører."
else
  echo "Tjenesten startet ikke som forventet. Viser status:"
  sudo systemctl --no-pager --full status "$SERVICE_NAME.service"
  exit 1
fi
