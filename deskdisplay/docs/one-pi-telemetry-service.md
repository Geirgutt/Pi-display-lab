# One-Pi secure telemetry service

The first bootstrap integration installs the existing
`deskdisplay/tools/secure_peer.c` sender on one selected cluster worker. The
sender remains the canonical protocol implementation. Ansible compiles it on
the worker into `/usr/local/libexec/pi-display-lab/secure_peer`, installs a
separate `deskdisplay-secure-peer.service`, and removes build-only packages
that were not already installed. The runtime needs only the normal system
OpenSSL libraries.

The feature is disabled by default and is deliberately bound to one worker in
the controller's ignored `config.local.json`:

```json
"deskdisplay": {
  "enabled": true,
  "worker": "worker-01.local",
  "port": 4567,
  "psk_file": "/etc/pi-display-lab/deskdisplay-peer.psk"
}
```

The PSK file is read on the controller, passed through the existing private
installation staging directory, and copied to the selected worker with mode
`0600`. It is never written to Git or included in the generated public config.
The worker copy uses `force: false`, so a normal reinstall/update preserves an
existing local PSK. Change the PSK deliberately on both the worker and the
DeskDisplay when rotation is needed.

Create the controller-side PSK before running the installer. Keep the command
outside the project directory:

```sh
sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 700 /etc/pi-display-lab
umask 077
openssl rand -hex 32 > /etc/pi-display-lab/deskdisplay-peer.psk
chmod 600 /etc/pi-display-lab/deskdisplay-peer.psk
```

Set `deskdisplay.enabled` and the exact worker address in `config.local.json`,
then run the normal installer. During the first physical test, limit the
worker installation explicitly:

```sh
bash scripts/install-cluster.sh --limit-worker worker-01.local
```

The selected worker listens on TCP port `4567` on all local interfaces. Open
that port in the worker firewall only if the lab firewall requires it. The
existing cluster worker, node-agent, controller and coordinator services are
separate units and are not replaced by the secure sender.

The secure sender is intentionally a listener: configure the DeskDisplay's
secure peer address to the selected worker's LAN address, enter the same PSK
over the serial console, and start the existing secure transport commands. The
sender emits the verified fixed frame once per second and reports the real
hostname, CPU, RAM, CPU/SoC temperature or unavailable, and uptime.

## Local training provider test

The server-side training boundary is implemented in `training.py`. A local JSON
file can exercise the same normalized state used by the web renderer:

```json
{
  "workouts": [
    {"date": "2026-09-07", "title": "Base Run", "activity_type": "Run", "duration_minutes": 42},
    {"date": "2026-09-09", "title": "Long Run", "activity_type": "Run", "duration_minutes": 65}
  ],
  "last_activity": {
    "date": "2026-09-06",
    "activity_type": "Run",
    "distance_km": 7.4,
    "duration_seconds": 2538,
    "average_pace_min_per_km": 5.68,
    "average_hr": 148
  }
}
```

Point the server at the file with `PI_DISPLAY_TRAINING_FILE`. Mock mode uses
the same shape with deterministic example data. Live DeskDisplay training
transport is intentionally deferred because the current verified secure frame
contains telemetry only; no Garmin authentication or scraping runs on the
ESP32.
