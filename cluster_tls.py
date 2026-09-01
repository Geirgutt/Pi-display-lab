"""TLS-oppsett for coordinator-trafikk.

Klientene stoler bare på lab-CA-en som installasjonen legger lokalt. Det finnes
bevisst ingen reserve som slår av verifisering: feil CA eller vertsnavn skal
stoppe forbindelsen i stedet for å gjøre den stille utrygg.
"""

from __future__ import annotations

import ssl
from pathlib import Path
from urllib.parse import urlsplit

from config import ClusterConfig


def create_client_ssl_context(config: ClusterConfig) -> ssl.SSLContext | None:
    """Lag en verifiserende klientkontekst, eller ingen for eksplisitt HTTP."""

    scheme = urlsplit(config.coordinator_url).scheme
    if scheme == "http":
        if config.tls_enabled:
            raise ValueError("TLS er aktivert, men coordinator_url bruker http")
        return None
    if scheme != "https" or not config.tls_enabled:
        raise ValueError("Coordinator-trafikk må bruke HTTPS når TLS er aktivert")

    ca_file = Path(config.ca_certificate_file)
    if not ca_file.is_file():
        raise OSError(f"Mangler lokal cluster-CA: {ca_file}")
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca_file))
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def create_server_ssl_context(config: ClusterConfig) -> ssl.SSLContext:
    """Lag coordinatorens serverkontekst fra lokalt sertifikat og privatnøkkel."""

    if not config.tls_enabled:
        raise ValueError("Coordinatoren skal ikke startes uten TLS")
    certificate = Path(config.server_certificate_file)
    private_key = Path(config.server_key_file)
    if not certificate.is_file() or not private_key.is_file():
        raise OSError("Coordinatorens TLS-sertifikat eller privatnøkkel mangler")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificate), str(private_key))
    return context
