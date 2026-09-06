#!/usr/bin/env bash
# Internal controller phase; invoked after credential collection by cluster_install.py.

set -Eeuo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Kjør installasjonen som vanlig controller-bruker, aldri som root."
  exit 1
fi

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ "$SCRIPT_SOURCE" == */* ]] || SCRIPT_SOURCE="./$SCRIPT_SOURCE"
PROJECT_DIR="$(cd -- "${SCRIPT_SOURCE%/*}/.." && pwd)"
CONFIG_FILE="${1:?Mangler config}"
TEMP_DIR="${2:?Mangler temp-mappe}"
REVISION="${3:?Mangler revisjon}"
VENV_DIR="$PROJECT_DIR/.venv"
REGENERATE_SERVER_CERT=false
[[ "${4:-}" != "--regenerate-server-cert" ]] || REGENERATE_SERVER_CERT=true
cd "$PROJECT_DIR"

# Never prompt after the initial credential phase, including in child scripts.
sudo() { command sudo -n "$@"; }
export -f sudo

echo "Installerer controller-avhengigheter ..."
source "$PROJECT_DIR/scripts/platform.sh"
platform_detect
platform_missing_packages
platform_install_packages
platform_setup_ansible

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
