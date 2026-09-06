#!/usr/bin/env bash
# Source this helper and call sudo_session_stop from the caller's EXIT trap.

sudo_session_start() {
  if ! command sudo -v; then
    echo "Trenger sudo-tilgang på controlleren." >&2
    return 1
  fi
  (
    trap 'kill "${sudo_sleep_pid:-}" 2>/dev/null || true; exit 0' TERM INT
    while kill -0 "$$" 2>/dev/null; do
      sleep 45 &
      sudo_sleep_pid=$!
      wait "$sudo_sleep_pid" || exit
      if ! command sudo -n -v </dev/null; then
        echo "Sudo-tilgangen utløp. Kjør oppdateringen på nytt for å autentisere." >&2
        exit 1
      fi
    done
  ) &
  SUDO_SESSION_PID=$!

  # Child installers must fail clearly rather than ask for a password later.
  sudo() { command sudo -n "$@"; }
  export -f sudo
}

sudo_session_stop() {
  if [[ -n "${SUDO_SESSION_PID:-}" ]]; then
    kill "$SUDO_SESSION_PID" 2>/dev/null || true
    wait "$SUDO_SESSION_PID" 2>/dev/null || true
  fi
}
