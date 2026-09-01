"""Tester lasting og identitetsbinding for lokale cluster-credentials."""

import json
import secrets
import tempfile
import unittest
from pathlib import Path

from cluster_auth import bearer_token, load_cluster_credentials


class ClusterAuthenticationTests(unittest.TestCase):
    def test_controller_credentials_authenticate_only_matching_identity(self) -> None:
        admin_token = secrets.token_urlsafe(32)
        worker_a = secrets.token_urlsafe(32)
        worker_b = secrets.token_urlsafe(32)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            path.write_text(
                json.dumps(
                    {
                        "admin_token": admin_token,
                        "workers": {"worker-01": worker_a, "worker-02": worker_b},
                    }
                ),
                encoding="utf-8",
            )
            credentials = load_cluster_credentials(path)

        self.assertTrue(credentials.authenticate_admin(admin_token))
        self.assertTrue(credentials.authenticate_worker("worker-01", worker_a))
        self.assertFalse(credentials.authenticate_worker("worker-02", worker_a))
        self.assertFalse(credentials.authenticate_worker("worker-01", worker_b))

    def test_missing_or_invalid_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = load_cluster_credentials(Path(directory) / "missing.json")
            invalid_path = Path(directory) / "invalid.json"
            invalid_path.write_text("{}", encoding="utf-8")
            invalid = load_cluster_credentials(invalid_path)

        self.assertFalse(missing.authenticate_admin(secrets.token_urlsafe(32)))
        self.assertFalse(invalid.authenticate_worker("worker-01", secrets.token_urlsafe(32)))

    def test_bearer_header_is_strict(self) -> None:
        token = secrets.token_urlsafe(32)
        self.assertEqual(bearer_token(f"Bearer {token}"), token)
        self.assertEqual(bearer_token(token), "")
        self.assertEqual(bearer_token("Basic value"), "")


if __name__ == "__main__":
    unittest.main()
