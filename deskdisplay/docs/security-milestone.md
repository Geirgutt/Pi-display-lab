# Secure transport foundation

This optional milestone establishes the long-term security boundary before
external telemetry or control features are added. It does not change the
verified display, touch, UI, Wi-Fi or BLE implementations. The secure build is
not the default build, and no device was flashed or committed during this
milestone.

## Physical verification update

The secure Wi-Fi build was tested on the real device. The following behavior is
now physically verified:

- TLS handshake and authenticated TLS session
- encrypted telemetry delivery
- increasing application sequence numbers
- peer disconnect handling
- automatic reconnect
- reconnect after multiple failed attempts
- stable heap across reconnect cycles
- explicit secure stop
- no visible PSRAM leak during testing

Display, touch and existing Wi-Fi behavior remained available during the secure
transport test. No visible PSRAM regression was observed. The longer telemetry
run below adds the first measured active-session heap and PSRAM values.

The subsequent secure telemetry run physically verified the application path
and measured approximately 248.8 KB free internal heap during the active TLS
session, 239.2–239.5 KB minimum heap, a 233460-byte largest block, 476004 bytes
of PSRAM used and a 946400-byte sketch. With the peer unavailable, free heap
returned to about 284144 bytes; after automatic reconnect it returned to about
248816 bytes. The Cluster page, sequence handling, offline timeout and
reconnect remained stable.

The final telemetry retest confirmed the corrected secure path on the real
device: the hostname displayed exactly `fedora`, TLS reconnect restored live
telemetry after `secure_peer` was restarted, and Wi-Fi, UI and touch remained
responsive. Active telemetry measured about 248800 bytes free internal heap,
239184 bytes minimum heap, a 233460-byte largest block and 476004 bytes of
PSRAM used, with no progressive loss. Temperature no longer uses the Fedora
`acpitz` value (observed as a constant 25.0 C); recognized CPU/package sources
varied approximately 57–69 C, and unsupported hosts display `N/A`.

## Baseline inspected

The project uses PlatformIO 6.1.19, Espressif32 platform 7.1.0, Arduino-ESP32
`3.20017.241212+sha.dcc1105b`, and the installed LovyanGFX 1.2.28. The ESP32-S3
SDK configuration contains mbedTLS TLS client/server support, PSK modes,
ECDHE/DHE-PSK, AES-GCM and the normal hardware AES/SHA acceleration. The
Arduino framework exposes `WiFiClientSecure::setPreSharedKey()` and the
framework-bundled `Preferences` NVS store. No secure-session library was added.

## Architecture choice

The chosen transport is one outbound TCP connection from the ESP32 to one
configured Linux/Raspberry Pi peer. The peer sends telemetry over that same
bidirectional TLS stream. The ESP32 does not listen for a new application port;
this keeps idle cost and LAN attack surface smaller while leaving the channel
available for future authenticated requests and control replies.

The ESP32 uses the installed `WiFiClientSecure` wrapper with TLS 1.2 PSK. The
Linux test peer uses OpenSSL and selects `ECDHE-PSK-AES128-CBC-SHA256`. This gives
mutual possession authentication through the 32-byte PSK, TLS record integrity
and encryption, fresh per-session keys, and forward secrecy from an ephemeral
ECDHE key. The installed mbedTLS/OpenSSL combination did not negotiate the
available DHE-PSK-GCM suite in a local TLS interop test; the ECDHE-PSK suite
did negotiate successfully and uses X25519 on the host.
TLS record sequence numbers reject reordered/replayed records within a session;
a new handshake creates a new TLS key context.

The application layer is deliberately separate from TLS:

```text
TLS 1.2 PSK session
    -> fixed 58-byte versioned frame
    -> telemetry type (currently type 1 only)
    -> future control types (reserved at 0x80 and above)
```

The current frame contains a bounded hostname, CPU percentage, temperature, RAM
percentage, uptime, online flag and a 64-bit application sequence. The ESP32
requires a strictly increasing sequence within each newly established TLS
session. A replayed sequence is dropped. Unknown/control-class messages are
rejected and counted as unauthorized; no control command is implemented.
Malformed, oversized, unauthenticated and timed-out input closes the session.
There is no plaintext fallback or downgrade path.

## Alternatives considered

| Option | Advantages | Reason not selected |
|---|---|---|
| UDP + PSK AEAD | Lowest connection overhead and easy one-way telemetry | Would require us to design and maintain nonce allocation, replay windows, peer/session authentication and reconnect semantics around raw datagrams. A mistake would become the security protocol. |
| TCP + custom AEAD | Could be smaller than TLS | Still requires a custom handshake, key separation, nonce schedule, authentication and failure handling. The installed mbedTLS already solves these problems. |
| Noise-style session | Good modern security properties and forward secrecy | No reviewed Noise implementation is installed in this Arduino project. Adding and maintaining one for a single peer would increase dependency and review risk. |
| TLS | Mature protocol, standard Linux/OpenSSL interoperability, record replay protection, session separation and established PSK APIs | More flash and connection-time heap than a bespoke datagram format, measured below. This is the acceptable cost for a long-lived secure foundation. |

TLS was chosen because it is the smallest mature construction already present in
the installed stack that covers both telemetry and future authenticated RPC.
The selected suite uses CBC+HMAC rather than an AEAD record cipher because no
interoperable ECDHE-PSK-GCM suite is exposed by this installed combination; this
must be rechecked if the framework is upgraded.

## Key handling

The PSK is never compiled into source. Install it through the bounded serial
command `secure key <64 hexadecimal characters>`. The command is not echoed and
the line buffer is cleared after submission. The ESP32 stores the 32-byte value
in the `dd-secure` NVS namespace and keeps only the runtime key copy required by
TLS. The peer stores the same hex value in a Linux file with mode `0600`.

`secure peer IPv4 PORT` stores the single peer endpoint. Replacing the PSK
overwrites the NVS value; the next `secure start` creates a new TLS session.
There is no provisioning UI, discovery, multi-user store or rotation protocol
yet. The current project does not enable encrypted NVS/flash encryption, so this
test foundation must not be treated as production secret protection against
physical flash extraction. Enabling ESP32 flash/NVS encryption is a required
hardening milestone before deployment outside a controlled test device.

## Resource measurement

The secure build is optional and does not alter the normal default, Wi-Fi, BLE or
Wi-Fi+BLE builds. PlatformIO sizes from the current clean build are:

| Build | Flash | Static RAM | Change |
|---|---:|---:|---:|
| UI Wi-Fi baseline | 788533 bytes | 45172 bytes | — |
| UI secure Wi-Fi | 946405 bytes | 47968 bytes | +157872 flash / +2796 RAM |

The default UI build remains 373209 bytes flash / 20676 bytes static RAM; the
secure source stubs add only 52 flash bytes and no static RAM. The connected TLS
context, record buffers and handshake allocations are created by
`WiFiClientSecure` only after `secure start` connects. No new FreeRTOS task,
timer, PSRAM buffer or third-party dependency was introduced. The application
polls the existing connection from the 50 Hz loop; telemetry is accepted at
the sender's intended one-second cadence and does no cryptographic work while
idle or disconnected.

Runtime free-heap, minimum heap, PSRAM and CPU cost still require physical
measurement on the known-good device. The next test must record them before
secure start, during handshake, during a stable one-update-per-second session,
after timeout and after reconnect.

## Files

- `src/secure_transport.*`: optional PSK/TLS lifecycle, NVS configuration,
  bounded parser, timeout, sequence check and counters.
- `src/secure_protocol.h`: fixed telemetry frame format; no serialization
  framework.
- `tools/secure_peer.c`: OpenSSL Linux/Raspberry Pi TLS peer and telemetry sender.
- `tools/tls_corrupt_proxy.py`: negative test proxy that flips one TLS ciphertext
  byte without terminating TLS.
- `platformio.ini`: optional `guition-4848s040-secure` build.
- `src/app.cpp` and `src/console.cpp`: service and test commands only.

No dashboard telemetry page, control/RPC operation, reboot action, discovery,
provisioning UI, OTA, Home Assistant integration or BLE transport was added.

## Build and test commands

Build the optional firmware and Linux peer without flashing:

```text
/home/geir/.platformio/penv/bin/pio run -e guition-4848s040-secure
cc -O2 -Wall -Wextra -Isrc -o tools/secure_peer tools/secure_peer.c -lssl -lcrypto
```

On Linux/Raspberry Pi, create a restricted PSK file out of the repository:

```sh
install -d -m 700 ~/.config/deskdisplay
umask 077
openssl rand -hex 32 > ~/.config/deskdisplay/peer.psk
chmod 600 ~/.config/deskdisplay/peer.psk
```

Enter the exact same value over the device serial console, then configure the
peer and start Wi-Fi and TLS:

```text
secure key <contents of ~/.config/deskdisplay/peer.psk>
secure peer <Linux-peer-IP> 4567
w
secure start
secure status
```

Run the peer:

```sh
./tools/secure_peer --psk-file ~/.config/deskdisplay/peer.psk
```

Expected valid traffic is `Secure TLS session established` on the peer and
`Secure telemetry ...` lines on the ESP32. `secure status` reports accepted,
authentication-failure, replay, malformed, unauthorized and reconnect counters.

Negative tests:

1. **Wrong key:** replace the peer file with a different 64-character value and
   restart the peer. The ESP32 must fail the TLS handshake, accept no telemetry,
   and increase `auth-fail` while retrying.
2. **Modified ciphertext:** run the peer on port 4567 and the proxy on 4568,
   configure the ESP32 peer to the proxy, and start:
   `python3 tools/tls_corrupt_proxy.py --target <Linux-peer-IP>`. The proxy flips
   one encrypted application-record byte. The TLS record must fail authentication,
   no telemetry may be accepted, and the ESP32 must reconnect.
3. **Replay:** run `./tools/secure_peer --psk-file FILE --replay-once`. The
   duplicate application sequence must be dropped and `replay` must increase.
4. **Malformed frame:** run `./tools/secure_peer --psk-file FILE
   --malformed-once`. The TLS session is authenticated, but the invalid frame
   must be dropped and `malformed` must increase.
5. **Disconnect/reconnect:** stop the peer or remove Wi-Fi, confirm the existing
   display/touch UI remains responsive, then restore the peer/Wi-Fi and confirm
   a fresh TLS session and increasing sequence values are accepted.

Do not flash during the software build step. Physical testing must use the
optional secure environment and preserve the existing display/touch regression
checks. Record free/minimum/largest internal heap and PSRAM at each state, plus
the secure status counters.

## Remaining risks and next step

The installed Arduino wrapper exposes `WiFiClientSecure::lastError()` but does
not expose a detailed TLS alert classification. The transport treats `0`/`-1`
and the wrapper's mbedTLS socket/connect/send/receive/reset errors as
`transport-fail`; other negative mbedTLS results during TLS setup/handshake are
counted as `auth-fail`. Errors while reading an established session are counted
as transport failures because the wrapper does not expose their individual
record-layer cause. A wrong-PSK test is still required to confirm the expected
`auth-fail` classification on the device. The test peer is a single PSK identity
and the ESP32 trusts the configured endpoint by address; LAN DNS, discovery and
multi-peer authorization are intentionally absent.

The next milestone should physically validate this secure build and measure
handshake/connected resource cost. After that, add a small telemetry page fed
from `lastTelemetry()`, then design encrypted NVS/flash-encryption provisioning
before adding any authenticated control command.
