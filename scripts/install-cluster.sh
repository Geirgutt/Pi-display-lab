#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
CONFIG_FILE="$PROJECT_DIR/config.local.json"
VENV_DIR="$PROJECT_DIR/.venv"
TEMP_DIR="$(mktemp -d)"
chmod 0700 "$TEMP_DIR"
trap 'rm -rf "$TEMP_DIR"' EXIT

REGENERATE_SERVER_CERT=false
CONTROLLER_ONLY=false
LIMIT_WORKERS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
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
if command -v python3 >/dev/null 2>&1; then
  python3 scripts/prepare-ansible.py \
    "$CONFIG_FILE" \
    "$TEMP_DIR" \
    --revision "$REVISION"
fi

echo "Kontrollerer lokal sudo-tilgang ..."
if ! sudo -v; then
  echo "Installasjonen trenger vanlig sudo-tilgang på controlleren."
  exit 1
fi

echo "Installerer controller-avhengigheter ..."
sudo apt-get update
sudo apt-get install -y ansible curl git openssl python3 python3-venv

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check -r requirements.txt

if [[ ! -f "$TEMP_DIR/vars.json" ]]; then
  "$VENV_DIR/bin/python" scripts/prepare-ansible.py \
    "$CONFIG_FILE" \
    "$TEMP_DIR" \
    --revision "$REVISION"
fi

echo "Kjører SSH- og nettverkspreflight uten å endre workerne ..."
"$VENV_DIR/bin/python" scripts/preflight-cluster.py \
  "$CONFIG_FILE" \
  "$TEMP_DIR/worker-identities.json"

echo "Klargjør privat CA og coordinator-sertifikat ..."
PKI_ARGS=()
if [[ "$REGENERATE_SERVER_CERT" == "true" ]]; then
  PKI_ARGS+=(--regenerate-server)
fi
"$VENV_DIR/bin/python" scripts/manage-cluster-pki.py \
  "$CONFIG_FILE" \
  "$TEMP_DIR" \
  "${PKI_ARGS[@]}"

echo "Genererer eventuelle manglende lokale credentials ..."
"$VENV_DIR/bin/python" scripts/generate-cluster-secrets.py \
  "$CONFIG_FILE" \
  "$TEMP_DIR/worker-identities.json" \
  "$TEMP_DIR"

RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"
CREDENTIALS_FILE="$("$VENV_DIR/bin/python" scripts/config-value.py cluster_credentials_file --config "$CONFIG_FILE")"
CREDENTIALS_DIR="${CREDENTIALS_FILE%/*}"
CA_FILE="$("$VENV_DIR/bin/python" scripts/config-value.py cluster_ca_file --config "$CONFIG_FILE")"
SERVER_CERT_FILE="$("$VENV_DIR/bin/python" scripts/config-value.py cluster_server_cert_file --config "$CONFIG_FILE")"
SERVER_KEY_FILE="$("$VENV_DIR/bin/python" scripts/config-value.py cluster_server_key_file --config "$CONFIG_FILE")"
PKI_DIR="${CA_FILE%/*}"
chmod 0600 "$CONFIG_FILE"
sudo install -d -o "$RUN_USER" -g "$RUN_GROUP" -m 0700 "$CREDENTIALS_DIR"
sudo install -o "$RUN_USER" -g "$RUN_GROUP" -m 0600 \
  "$TEMP_DIR/cluster-credentials.json" \
  "$CREDENTIALS_FILE"
sudo install -d -o "$RUN_USER" -g "$RUN_GROUP" -m 0700 "$PKI_DIR"
sudo install -o "$RUN_USER" -g "$RUN_GROUP" -m 0600 "$TEMP_DIR/ca.key" "$PKI_DIR/ca.key"
sudo install -o "$RUN_USER" -g "$RUN_GROUP" -m 0644 "$TEMP_DIR/ca.crt" "$CA_FILE"
sudo install -o "$RUN_USER" -g "$RUN_GROUP" -m 0600 "$TEMP_DIR/coordinator.key" "$SERVER_KEY_FILE"
sudo install -o "$RUN_USER" -g "$RUN_GROUP" -m 0644 "$TEMP_DIR/coordinator.crt" "$SERVER_CERT_FILE"
if [[ -f "$TEMP_DIR/node-heartbeat.env" ]]; then
  sudo install -o "$RUN_USER" -g "$RUN_GROUP" -m 0600 \
    "$TEMP_DIR/node-heartbeat.env" \
    /etc/pi-display-lab/node-heartbeat.env
fi

echo "Installerer controller-tjenestene (controlleren blir ikke worker) ..."
bash scripts/install-service.sh
bash scripts/install-coordinator-service.sh

echo "Installerer workerne med eksakt controller-commit $REVISION ..."
mapfile -t WORKERS < <(
  "$VENV_DIR/bin/python" scripts/config-value.py worker_hosts --config "$CONFIG_FILE"
)
for WORKER in "${WORKERS[@]}"; do
  if [[ "$CONTROLLER_ONLY" == "true" ]]; then
    continue
  fi
  if [[ ${#LIMIT_WORKERS[@]} -gt 0 ]]; then
    SELECTED=false
    for LIMITED_WORKER in "${LIMIT_WORKERS[@]}"; do
      [[ "$WORKER" == "$LIMITED_WORKER" ]] && SELECTED=true
    done
    [[ "$SELECTED" == "true" ]] || continue
  fi
  BECOME_ARGS=()
  if ! ansible "$WORKER" \
    -i "$TEMP_DIR/inventory.ini" \
    -m ansible.builtin.raw \
    -a "sudo -n /usr/bin/true" >/dev/null 2>&1; then
    echo "$WORKER trenger sitt eget sudo-passord. Passordet lagres ikke."
    BECOME_ARGS+=(--ask-become-pass)
  fi
  echo "Installerer $WORKER ..."
  if ! ansible-playbook \
    -i "$TEMP_DIR/inventory.ini" \
    ansible/install-workers.yml \
    --limit "$WORKER" \
    --extra-vars "@$TEMP_DIR/vars.json" \
    --extra-vars "@$TEMP_DIR/worker-secrets.json" \
    "${BECOME_ARGS[@]}"; then
    echo "Worker-installasjonen feilet for $WORKER. Kontroller SSH og sudo-passord."
    exit 1
  fi
done

echo
bash scripts/verify-cluster.sh
