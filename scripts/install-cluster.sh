#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
CONFIG_FILE="$PROJECT_DIR/config.local.json"
TEMP_DIR="$(mktemp -d)"
chmod 0700 "$TEMP_DIR"
source "$PROJECT_DIR/scripts/sudo-session.sh"
trap 'sudo_session_stop; rm -rf "$TEMP_DIR"' EXIT

REGENERATE_SERVER_CERT=false
CONTROLLER_ONLY=false
LIMIT_WORKERS=()
SUDO_SOCKET=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sudo-socket)
      [[ $# -ge 2 ]] || { echo "--sudo-socket mangler verdi"; exit 2; }
      SUDO_SOCKET="$2"
      shift 2
      ;;
    --regenerate-server-cert)
      REGENERATE_SERVER_CERT=true
      shift
      ;;
    --controller-only)
      CONTROLLER_ONLY=true
      shift
      ;;
    --limit-worker)
      [[ $# -ge 2 ]] || { echo "--limit-worker mangler verdi"; exit 2; }
      LIMIT_WORKERS+=("$2")
      shift 2
      ;;
    *)
      echo "Ukjent valg: $1"
      exit 2
      ;;
  esac
done

if [[ $EUID -eq 0 ]]; then
  echo "Kjør installasjonen som vanlig controller-bruker, aldri som root."
  exit 1
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Mangler config.local.json. Start med: cp config.example.json config.local.json"
  exit 1
fi

cd "$PROJECT_DIR"
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  echo "Installasjonen stoppet: prosjektmappen har lokale Git-endringer."
  echo "Kontroller dem med: git status"
  exit 1
fi

REVISION="$(git rev-parse HEAD)"
python3 scripts/prepare-ansible.py \
  "$CONFIG_FILE" \
  "$TEMP_DIR" \
  --revision "$REVISION"

echo "Kontrollerer lokal sudo-tilgang ..."
sudo_session_start

INSTALL_ARGS=()
[[ -z "$SUDO_SOCKET" ]] || INSTALL_ARGS+=(--sudo-socket "$SUDO_SOCKET")
[[ "$REGENERATE_SERVER_CERT" != "true" ]] || INSTALL_ARGS+=(--regenerate-server-cert)
[[ "$CONTROLLER_ONLY" != "true" ]] || INSTALL_ARGS+=(--controller-only)
for WORKER in "${LIMIT_WORKERS[@]}"; do
  INSTALL_ARGS+=(--limit-worker "$WORKER")
done
python3 cluster_install.py "$CONFIG_FILE" "$TEMP_DIR" "$REVISION" "${INSTALL_ARGS[@]}"

echo
bash scripts/verify-cluster.sh
