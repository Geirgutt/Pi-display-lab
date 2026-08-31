"""Tester API-broen til den separate cluster coordinatoren."""

import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from app import create_app
from config import AppConfig, ClusterConfig


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class ClusterApiTests(unittest.TestCase):
    def test_disabled_cluster_returns_controlled_status(self) -> None:
        app = create_app(mock_mode=True, settings=AppConfig())
        response = app.test_client().get("/api/cluster-jobs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "disabled")
        self.assertEqual(response.get_json()["results"], [])

    @patch("cluster_client.urlopen")
    def test_available_coordinator_data_is_returned(self, mocked_urlopen) -> None:
        expected = {
            "completed": 3,
            "queued": 0,
            "results": [
                {
                    "job_id": 1,
                    "worker": "cluster-pi3-02",
                    "start": 1,
                    "end": 100000,
                    "prime_count": 9592,
                }
            ],
        }
        mocked_urlopen.return_value = FakeResponse(expected)
        settings = AppConfig(ClusterConfig(True, "http://127.0.0.1:5001"))
        response = create_app(mock_mode=True, settings=settings).test_client().get(
            "/api/cluster-jobs"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        self.assertEqual(mocked_urlopen.call_args.kwargs["timeout"], 2.0)

    @patch("cluster_client.urlopen", side_effect=URLError("offline"))
    def test_unavailable_coordinator_does_not_break_app(self, _mocked_urlopen) -> None:
        settings = AppConfig(ClusterConfig(True, "http://127.0.0.1:5001"))
        client = create_app(mock_mode=True, settings=settings).test_client()

        cluster_response = client.get("/api/cluster-jobs")
        self.assertEqual(cluster_response.status_code, 502)
        self.assertEqual(cluster_response.get_json()["status"], "unavailable")
        self.assertEqual(client.get("/api/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
