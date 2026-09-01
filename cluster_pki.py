"""Lokal privat CA og serversertifikat for det betrodde labnettet."""

from __future__ import annotations

import ipaddress
import os
import shutil
import ssl
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from config import AppConfig


@dataclass(frozen=True)
class PkiStatus:
    ca_exists: bool
    ca_is_valid: bool
    server_exists: bool
    server_matches_address: bool
    server_is_current: bool


def _decode_certificate(certificate: str | Path) -> dict[str, object]:
    try:
        return ssl._ssl._test_decode_cert(str(certificate))  # type: ignore[attr-defined]
    except (OSError, ssl.SSLError, ValueError):
        return {}


def certificate_matches_address(certificate: str | Path, address: str) -> bool:
    """Sjekk SAN uten å slå av eller etterligne klientens TLS-verifisering."""

    decoded = _decode_certificate(certificate)
    if not decoded:
        return False
    entries = decoded.get("subjectAltName", ())
    try:
        expected_ip = ipaddress.ip_address(address)
    except ValueError:
        expected_ip = None
    if expected_ip is not None:
        return any(
            kind == "IP Address" and value == str(expected_ip)
            for kind, value in entries
        )
    return any(
        kind == "DNS" and value.rstrip(".").casefold() == address.rstrip(".").casefold()
        for kind, value in entries
    )


def certificate_is_current(certificate: str | Path, minimum_seconds: int) -> bool:
    decoded = _decode_certificate(certificate)
    not_after = decoded.get("notAfter")
    if not isinstance(not_after, str):
        return False
    try:
        expires_at = ssl.cert_time_to_seconds(not_after)
    except ValueError:
        return False
    return expires_at - time.time() >= minimum_seconds


def inspect_pki(settings: AppConfig) -> PkiStatus:
    cluster = settings.cluster
    ca_key = Path(cluster.ca_certificate_file).with_name("ca.key")
    ca_cert = Path(cluster.ca_certificate_file)
    server_cert = Path(cluster.server_certificate_file)
    server_key = Path(cluster.server_key_file)
    ca_exists = ca_key.exists() or ca_cert.exists()
    ca_is_valid = ca_key.is_file() and ca_cert.is_file() and _valid_ca(ca_cert, ca_key)
    server_exists = server_cert.is_file() and server_key.is_file()
    return PkiStatus(
        ca_exists=ca_exists,
        ca_is_valid=ca_is_valid,
        server_exists=server_exists,
        server_matches_address=(
            server_exists
            and certificate_matches_address(server_cert, settings.controller_host)
        ),
        server_is_current=(
            server_exists
            and ca_is_valid
            and certificate_is_current(server_cert, 7 * 24 * 60 * 60)
            and _valid_server(server_cert, server_key, ca_cert, settings.controller_host)
        ),
    )


def _run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=30,
        )
    except FileNotFoundError as error:
        raise RuntimeError("Fant ikke openssl på controlleren") from error
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("OpenSSL kunne ikke validere eller lage cluster-PKI") from error


def _same_public_key(certificate: Path, private_key: Path) -> bool:
    try:
        cert_public = _run(
            ["openssl", "x509", "-in", str(certificate), "-pubkey", "-noout"],
        ).stdout
        key_public = _run(
            ["openssl", "pkey", "-in", str(private_key), "-pubout"],
        ).stdout
    except RuntimeError:
        return False
    return bool(cert_public and cert_public == key_public)


def _valid_ca(certificate: Path, private_key: Path) -> bool:
    if not certificate.is_file() or not private_key.is_file():
        return False
    try:
        _run(["openssl", "x509", "-in", str(certificate), "-checkend", "2592000", "-noout"])
    except RuntimeError:
        return False
    return _same_public_key(certificate, private_key)


def _valid_server(
    certificate: Path,
    private_key: Path,
    ca_certificate: Path,
    address: str,
) -> bool:
    if not certificate.is_file() or not private_key.is_file():
        return False
    try:
        _run(["openssl", "verify", "-CAfile", str(ca_certificate), str(certificate)])
        _run(["openssl", "x509", "-in", str(certificate), "-checkend", "604800", "-noout"])
    except RuntimeError:
        return False
    return _same_public_key(certificate, private_key) and certificate_matches_address(
        certificate, address
    )


def _copy_private(source: Path, destination: Path, mode: int) -> None:
    shutil.copyfile(source, destination)
    os.chmod(destination, mode)


def prepare_pki(
    settings: AppConfig,
    output_dir: str | Path,
    *,
    allow_server_regeneration: bool = False,
) -> dict[str, bool]:
    """Bevar gyldig CA/serversertifikat eller lag det som mangler i staging."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    os.chmod(output, 0o700)
    cluster = settings.cluster
    source_ca = Path(cluster.ca_certificate_file)
    source_ca_key = source_ca.with_name("ca.key")
    source_server = Path(cluster.server_certificate_file)
    source_server_key = Path(cluster.server_key_file)
    staged_ca = output / "ca.crt"
    staged_ca_key = output / "ca.key"
    staged_server = output / "coordinator.crt"
    staged_server_key = output / "coordinator.key"

    any_ca = source_ca.exists() or source_ca_key.exists()
    if any_ca and not _valid_ca(source_ca, source_ca_key):
        raise RuntimeError(
            "Eksisterende cluster-CA er ufullstendig eller ugyldig. "
            "Den erstattes ikke automatisk."
        )
    ca_preserved = any_ca
    if ca_preserved:
        _copy_private(source_ca, staged_ca, 0o644)
        _copy_private(source_ca_key, staged_ca_key, 0o600)
    else:
        _run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:3072", "-sha256",
                "-days", "3650", "-nodes", "-keyout", str(staged_ca_key),
                "-out", str(staged_ca), "-subj", "/CN=Pi Display Lab Private CA",
                "-addext", "basicConstraints=critical,CA:TRUE",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            ]
        )
        os.chmod(staged_ca_key, 0o600)
        os.chmod(staged_ca, 0o644)

    server_valid = _valid_server(
        source_server,
        source_server_key,
        staged_ca,
        settings.controller_host,
    )
    any_server = source_server.exists() or source_server_key.exists()
    if server_valid:
        _copy_private(source_server, staged_server, 0o644)
        _copy_private(source_server_key, staged_server_key, 0o600)
    else:
        if any_server and not allow_server_regeneration:
            raise RuntimeError(
                "Coordinator-sertifikatet er ugyldig, utløper snart eller matcher ikke "
                "controller-adressen. Kjør setup-veiviseren og godkjenn regenerering."
            )
        san_kind = "IP" if _is_ip(settings.controller_host) else "DNS"
        request_file = output / "coordinator.csr"
        extension_file = output / "coordinator.ext"
        extension_file.write_text(
            "\n".join(
                (
                    "basicConstraints=critical,CA:FALSE",
                    "keyUsage=critical,digitalSignature,keyEncipherment",
                    "extendedKeyUsage=serverAuth",
                    f"subjectAltName={san_kind}:{settings.controller_host}",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        _run(
            [
                "openssl", "req", "-new", "-newkey", "rsa:3072", "-nodes",
                "-keyout", str(staged_server_key), "-out", str(request_file),
                "-subj", "/CN=Pi Display Lab Coordinator",
            ]
        )
        _run(
            [
                "openssl", "x509", "-req", "-sha256", "-days", "825",
                "-in", str(request_file), "-CA", str(staged_ca),
                "-CAkey", str(staged_ca_key), "-CAcreateserial",
                "-out", str(staged_server), "-extfile", str(extension_file),
            ]
        )
        os.chmod(staged_server_key, 0o600)
        os.chmod(staged_server, 0o644)
        request_file.unlink(missing_ok=True)
        extension_file.unlink(missing_ok=True)
        (output / "ca.srl").unlink(missing_ok=True)

    if not _valid_server(
        staged_server,
        staged_server_key,
        staged_ca,
        settings.controller_host,
    ):
        raise RuntimeError("Det genererte coordinator-sertifikatet kunne ikke valideres")
    return {"ca_preserved": ca_preserved, "server_preserved": server_valid}


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True
