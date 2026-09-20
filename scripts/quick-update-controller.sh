#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"

if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "Hurtigoppdatering kan ikke brukes: controllerens .venv mangler." >&2
  echo "Kjør full oppdatering." >&2
  exit 2
fi

for service in pi-display-lab.service cluster-coordinator.service; do
  if ! systemctl cat "$service" >/dev/null 2>&1; then
    echo "Hurtigoppdatering kan ikke brukes: $service er ikke installert." >&2
    echo "Kjør full oppdatering." >&2
    exit 2
  fi
done

echo "Restarter bare controllerens runtime-tjenester ..."
sudo -n systemctl restart pi-display-lab.service cluster-coordinator.service
systemctl is-active --quiet pi-display-lab.service
systemctl is-active --quiet cluster-coordinator.service
