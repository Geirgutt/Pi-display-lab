# Controller secure cluster telemetry gateway

The first bootstrap integration installs the existing
`deskdisplay/tools/secure_peer.c` sender on the controller. The sender remains
the canonical protocol implementation. The controller-side service reads a
compact loopback snapshot from the main Flask app and sends the controller and
all configured workers over one authenticated TLS connection to DeskDisplay.
The display receives pages of three nodes and rotates through them once per
second, so the number of workers is not limited by the physical screen layout.

The feature is disabled by default and is configured in the controller's
ignored `config.local.json`:

```json
"deskdisplay": {
  "enabled": true,
  "port": 4567,
  "psk_file": "/etc/pi-display-lab/deskdisplay-peer.psk"
}
```

The PSK file is read and used on the controller with mode `0600`. It is never
written to Git or distributed to workers. Change the PSK deliberately on both
the controller and the DeskDisplay when rotation is needed.

Set `deskdisplay.enabled` in `config.local.json`, then run the normal installer.
It creates a fresh 32-byte PSK locally on the controller when the file is
missing, preserves an existing valid PSK, and refuses to overwrite an invalid
one:

```sh
bash scripts/install-cluster.sh
```

With the display connected over USB, a PC with a checkout of this repository
can build, flash and provision the secure firmware. The display does not need
to be connected to the controller. The provisioning command fetches the PSK
from the controller over SSH into memory only; it is never written to the PC,
Git or the terminal. The optional Wi-Fi prompt is written only to the
display's local NVS:

```sh
bash scripts/provision-deskdisplay.sh \
  --port /dev/serial/by-id/usb-... \
  --controller-ssh pi@controller.local \
  --controller-host controller.local \
  --wifi-ssid "mitt-nettverk"
```

PlatformIO is installed into the ignored local `.display-venv/` if it is not
already available. Use `--display-no-flash` when the secure firmware is already
on the display. The provisioning sends the controller's locally generated PSK,
controller IPv4 address and gateway port over the serial console without
printing the PSK.

After this initial setup the display only needs USB-C power. A normal
`scripts/update.sh` updates the controller and workers, but does not flash the
display. Run the provisioning command again only when firmware or display-side
credentials must change.

The first `scripts/install-cluster.sh` or `scripts/update.sh` run asks whether
the display is connected over USB data. The answer and selected Pi are stored
in the ignored `config.local.json`; later updates reuse that choice. The first
yes-answer also asks for an optional Wi-Fi SSID; the password is requested
hidden and is not stored. If the display is assigned to a worker, the installer
runs the provisioning script on that worker after the worker update and sends
the PSK (and, when needed, Wi-Fi password) through private SSH stdin pipes. The
PSK is not installed as a worker credential or written to the worker's
repository.

The controller listens on TCP port `4567` on all local interfaces. Open that
port in the controller firewall only if the lab firewall requires it. The
existing cluster worker, node-agent and coordinator services remain separate.

The secure sender is intentionally a listener. The gateway emits a fixed
cluster frame once per second and reports the controller and all configured
workers. Missing heartbeats are shown offline; there is no two-worker limit.

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
