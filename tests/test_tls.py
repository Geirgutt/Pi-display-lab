"""Integrasjonstester for ekte CA-, vertsnavn- og HTTPS-verifisering."""

import json
import os
import shutil
import ssl
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cluster_client import ClusterCoordinatorClient, CoordinatorUnavailable
from cluster_pki import prepare_pki
from config import AppConfig, ClusterConfig


PROJECT_DIR = Path(__file__).resolve().parent.parent


class JsonHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"ok": True, "service": "cluster-coordinator"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        return


def find_openssl_dir() -> str:
    executable = shutil.which("openssl")
    if executable:
        return str(Path(executable).parent)
    candidates = (
        Path("C:/Program Files/Git/usr/bin/openssl.exe"),
        Path("C:/Program Files/Git/mingw64/bin/openssl.exe"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.parent)
    return ""


class ClusterTlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        openssl_dir = find_openssl_dir()
        if not openssl_dir:
            raise unittest.SkipTest("OpenSSL mangler")
        cls.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = openssl_dir + os.pathsep + cls.old_path
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        source = root / "source"
        stage = root / "stage"
        settings = AppConfig(
            cluster=ClusterConfig(
                enabled=True,
                coordinator_url="https://localhost:1",
                ca_certificate_file=str(source / "ca.crt"),
                server_certificate_file=str(source / "coordinator.crt"),
                server_key_file=str(source / "coordinator.key"),
            ),
            node_role="controller",
            controller_host="localhost",
            worker_hosts=("worker-01.example",),
            ssh_user="labuser",
        )
        prepare_pki(settings, stage)
        cls.ca = stage / "ca.crt"
        cls.cert = stage / "coordinator.crt"
        cls.key = stage / "coordinator.key"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), JsonHandler)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(cls.cert, cls.key)
        cls.server.socket = server_context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()
        os.environ["PATH"] = cls.old_path

    def client(self, hostname: str, ca_file: Path) -> ClusterCoordinatorClient:
        port = self.server.server_address[1]
        return ClusterCoordinatorClient(
            ClusterConfig(
                enabled=True,
                coordinator_url=f"https://{hostname}:{port}",
                ca_certificate_file=str(ca_file),
            ),
            bearer_token="x" * 32,
        )

    def test_correct_private_ca_and_hostname_succeed(self) -> None:
        self.assertTrue(self.client("localhost", self.ca).fetch_health()["ok"])

    def test_wrong_ca_fails_closed(self) -> None:
        root = Path(self.temp.name)
        other_source = root / "other-source"
        other_stage = root / "other-stage"
        settings = AppConfig(
            cluster=ClusterConfig(
                enabled=True,
                coordinator_url="https://other.invalid:1",
                ca_certificate_file=str(other_source / "ca.crt"),
                server_certificate_file=str(other_source / "coordinator.crt"),
                server_key_file=str(other_source / "coordinator.key"),
            ),
            controller_host="other.invalid",
        )
        prepare_pki(settings, other_stage)
        with self.assertRaises(CoordinatorUnavailable):
            self.client("localhost", other_stage / "ca.crt").fetch_health()

    def test_hostname_mismatch_fails_closed(self) -> None:
        with self.assertRaises(CoordinatorUnavailable):
            self.client("127.0.0.1", self.ca).fetch_health()

    def test_tls_enabled_client_refuses_plain_http(self) -> None:
        client = ClusterCoordinatorClient(
            ClusterConfig(
                enabled=True,
                coordinator_url="http://controller.example:5001",
                tls_enabled=True,
            )
        )
        with self.assertRaises(CoordinatorUnavailable):
            client.fetch_health()

    def test_valid_pki_is_preserved_across_reinstall(self) -> None:
        root = Path(self.temp.name)
        second = root / "second-stage"
        settings = AppConfig(
            cluster=ClusterConfig(
                enabled=True,
                coordinator_url="https://localhost:1",
                ca_certificate_file=str(self.ca),
                server_certificate_file=str(self.cert),
                server_key_file=str(self.key),
            ),
            controller_host="localhost",
        )
        result = prepare_pki(settings, second)
        self.assertEqual(result, {"ca_preserved": True, "server_preserved": True})
        self.assertEqual((second / "ca.key").read_bytes(), self.ca.with_name("ca.key").read_bytes())

    def test_no_insecure_verification_or_private_ca_worker_deployment(self) -> None:
        client_source = (PROJECT_DIR / "cluster_tls.py").read_text(encoding="utf-8")
        deployment = "\n".join(
            (PROJECT_DIR / path).read_text(encoding="utf-8")
            for path in (
                "ansible/install-workers.yml",
                "scripts/prepare-ansible.py",
                "scripts/generate-cluster-secrets.py",
            )
        )
        self.assertNotIn("verify=False", client_source)
        self.assertNotIn("CERT_NONE", client_source)
        self.assertNotIn("ca.key", deployment)
        self.assertIn("https://{{ controller_host }}", deployment)


if __name__ == "__main__":
    unittest.main()
