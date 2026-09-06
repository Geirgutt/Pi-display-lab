"""HTTP-laget: ruter mellom nettleseren og prosjektets state/transport."""

from __future__ import annotations

import argparse
import os
import secrets
from typing import Any

from flask import Flask, jsonify, render_template, request

from cluster_auth import load_cluster_credentials, valid_worker_id
from cluster_client import (
    CoordinatorAuthenticationError,
    ClusterCoordinatorClient,
    ClusterStatusCache,
    CoordinatorUnavailable,
    disabled_cluster_status,
)
from cluster_jobs import validate_monte_carlo, validate_prime_range, validate_slot_limit
from config import AppConfig, load_config
from display_state import DashboardState
from transports import BrowserTransport, Esp32Transport, TransportHub
from updates import UpdateManager


def create_app(
    mock_mode: bool | None = None,
    update_manager: UpdateManager | None = None,
    settings: AppConfig | None = None,
    coordinator_client: ClusterCoordinatorClient | None = None,
    cluster_status_cache: ClusterStatusCache | None = None,
) -> Flask:
    """Lag Flask-appen. Funksjonsformen gjør appen enkel å teste."""

    if mock_mode is None:
        mock_mode = os.name == "nt" or os.getenv("PI_DISPLAY_MOCK") == "1"

    app = Flask(__name__)
    app.config["MOCK_MODE"] = mock_mode
    app.config["NODE_TOKEN"] = os.getenv("PI_DISPLAY_NODE_TOKEN", "")

    settings = settings or load_config()
    dashboard = DashboardState(mock_mode=mock_mode)
    updater = update_manager or UpdateManager()
    cluster_credentials = load_cluster_credentials(settings.cluster.credentials_file)
    cluster = coordinator_client or ClusterCoordinatorClient(
        settings.cluster,
        bearer_token=cluster_credentials.admin_token,
    )
    cluster_status = cluster_status_cache or ClusterStatusCache(cluster)
    browser = BrowserTransport()
    esp32 = Esp32Transport(enabled=False)
    transports = TransportHub([browser, esp32])

    # Lagres i appen slik at testene (og vi senere) kan finne komponentene.
    app.extensions["dashboard"] = dashboard
    app.extensions["transports"] = transports
    app.extensions["updater"] = updater
    app.extensions["cluster_coordinator"] = cluster
    app.extensions["cluster_status"] = cluster_status

    @app.get("/")
    def index() -> str:
        return render_template("index.html", mock_mode=mock_mode)

    @app.get("/api/health")
    def health() -> Any:
        return jsonify({"ok": True, "mock_mode": mock_mode})

    @app.get("/api/state")
    def get_state() -> Any:
        payload = dashboard.snapshot(cluster_status=cluster_status.snapshot())
        transports.publish(payload)
        return jsonify(browser.latest())

    @app.post("/api/screen")
    def set_screen() -> Any:
        body = request.get_json(silent=True) or {}
        screen = body.get("screen")
        try:
            dashboard.set_screen(screen)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400

        payload = dashboard.snapshot(cluster_status=cluster_status.snapshot())
        transports.publish(payload)
        return jsonify({"ok": True, "state": browser.latest()})

    @app.post("/api/demo/start")
    def start_demo() -> Any:
        if not cluster.config.enabled:
            return jsonify({"ok": False, "error": "Cluster-integrasjonen er deaktivert"}), 409
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "Forventet et JSON-objekt"}), 400
        reserve_one = body.get("reserve_one", True)
        normalized = {
            "samples": body.get("samples", body.get("iterations", 10_000_000)),
            "slot_limit": body.get("slot_limit", body.get("cores", 1)),
            "reserve_one": reserve_one,
        }
        try:
            samples, samples_per_job, slot_limit = validate_monte_carlo(normalized)
            if not isinstance(reserve_one, bool):
                raise ValueError("reserve_one må være true eller false")
            capacity = dashboard.cluster_capacity(reserve_one)
            if slot_limit > capacity:
                raise ValueError(f"Bare {capacity} compute-slots er tilgjengelige")
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        try:
            result = cluster.start_monte_carlo({
                "samples": samples,
                "samples_per_job": samples_per_job,
                "slot_limit": slot_limit,
                "reserve_one": reserve_one,
            })
        except CoordinatorAuthenticationError:
            cluster_status.mark_unavailable("authentication_failed")
            return jsonify({"ok": False, "error": "Coordinator avviste lokal admin-credential"}), 502
        except CoordinatorUnavailable:
            cluster_status.mark_unavailable()
            return jsonify({"ok": False, "error": "Cluster coordinator svarer ikke"}), 502

        try:
            cluster_status.store(cluster.fetch_status())
        except CoordinatorUnavailable:
            cluster_status.invalidate()
        dashboard.set_screen("nerd")
        return jsonify(result), 202

    @app.post("/api/nodes/heartbeat")
    def node_heartbeat() -> Any:
        """Motta ferske systemmålinger fra en annen maskin på labnettet."""

        expected_token = app.config["NODE_TOKEN"]
        supplied_token = request.headers.get("X-Node-Token", "")
        if expected_token and not secrets.compare_digest(expected_token, supplied_token):
            return jsonify({"ok": False, "error": "Ugyldig node-token"}), 401

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "Forventet et JSON-objekt"}), 400
        if valid_worker_id(body.get("node_id")) in cluster_credentials.retired_worker_ids:
            return jsonify({"ok": False, "error": "Denne workeren er fjernet fra clusteret"}), 403
        try:
            node = dashboard.register_node(body, request.remote_addr)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        return jsonify({"ok": True, "node": node}), 202

    @app.get("/api/update/status")
    def update_status() -> Any:
        return jsonify(updater.status())

    @app.get("/api/cluster-jobs")
    def cluster_jobs() -> Any:
        if not cluster.config.enabled:
            return jsonify(disabled_cluster_status())

        try:
            payload = cluster.fetch_status()
            cluster_status.store(payload)
            return jsonify(payload)
        except CoordinatorAuthenticationError:
            payload = cluster_status.mark_unavailable("authentication_failed")
            return jsonify(payload), 502
        except CoordinatorUnavailable:
            payload = cluster_status.mark_unavailable()
            return (
                jsonify(payload),
                502,
            )

    @app.post("/api/cluster/start")
    def start_cluster_job() -> Any:
        if not cluster.config.enabled:
            return jsonify({"ok": False, "error": "Cluster-integrasjonen er deaktivert"}), 409
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "Forventet et JSON-objekt"}), 400
        try:
            start, end, chunk_size = validate_prime_range(body)
            slot_limit = validate_slot_limit(body)
            reserve_one = body.get("reserve_one", False)
            if not isinstance(reserve_one, bool):
                raise ValueError("reserve_one må være true eller false")
            if "slot_limit" in body:
                capacity = dashboard.cluster_capacity(reserve_one)
                if slot_limit > capacity:
                    raise ValueError(f"Bare {capacity} compute-slots er tilgjengelige")
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400

        try:
            result = cluster.start_prime_job(
                {
                    "start": start,
                    "end": end,
                    "chunk_size": chunk_size,
                    "slot_limit": slot_limit,
                    "reserve_one": reserve_one,
                }
            )
        except CoordinatorAuthenticationError:
            cluster_status.mark_unavailable("authentication_failed")
            return jsonify(
                {"ok": False, "error": "Coordinator avviste lokal admin-credential"}
            ), 502
        except CoordinatorUnavailable:
            cluster_status.mark_unavailable()
            return jsonify({"ok": False, "error": "Cluster coordinator svarer ikke"}), 502

        try:
            cluster_status.store(cluster.fetch_status())
        except CoordinatorUnavailable:
            cluster_status.invalidate()
        dashboard.set_screen("cluster")
        return jsonify(result), 202

    @app.post("/api/cluster/cancel/<int:batch_id>")
    def cancel_cluster_batch(batch_id: int) -> Any:
        if not cluster.config.enabled:
            return jsonify({"ok": False, "error": "Cluster-integrasjonen er deaktivert"}), 409
        try:
            result = cluster.cancel_batch(batch_id)
            cluster_status.store(cluster.fetch_status())
        except CoordinatorAuthenticationError:
            cluster_status.mark_unavailable("authentication_failed")
            return jsonify({"ok": False, "error": "Coordinator avviste lokal admin-credential"}), 502
        except CoordinatorUnavailable:
            cluster_status.mark_unavailable()
            return jsonify({"ok": False, "error": "Cluster coordinator svarer ikke"}), 502
        return jsonify(result), 202

    @app.post("/api/update/check")
    def update_check() -> Any:
        if not updater.check_async():
            return jsonify({"ok": False, "error": "En oppdateringsjobb kjører allerede"}), 409
        return jsonify({"ok": True, "message": "Oppdateringssjekk startet"}), 202

    @app.get("/api/protocol/example")
    def protocol_example() -> Any:
        """En kompakt eksempelmelding som senere ESP32-kode kan testes mot."""

        return jsonify(dashboard.protocol_example())

    return app


# Gjør også `flask --app app run` mulig. `python app.py` er anbefalt her.
app = create_app()


if __name__ == "__main__":
    runtime_settings = load_config()
    parser = argparse.ArgumentParser(description="Pi Display Lab")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="bruk stabile eksempeldata (nyttig på Windows)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=runtime_settings.app_port,
        help="HTTP-port (standard fra config.local.json)",
    )
    args = parser.parse_args()

    selected_app = create_app(
        mock_mode=True if args.mock else None,
        settings=runtime_settings,
    )
    mode = "MOCK" if selected_app.config["MOCK_MODE"] else "PI / LIVE"
    print(f"Pi Display Lab starter i {mode}-modus")
    print(f"Åpne http://127.0.0.1:{args.port} på denne maskinen")
    print("Fra en annen PC: bruk Pi-ens IP-adresse i stedet for 127.0.0.1")
    selected_app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)
