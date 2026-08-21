"""HTTP-laget: ruter mellom nettleseren og prosjektets state/transport."""

from __future__ import annotations

import argparse
import os
import secrets
from typing import Any

from flask import Flask, jsonify, render_template, request

from display_state import DashboardState
from transports import BrowserTransport, Esp32Transport, TransportHub
from updates import UpdateManager


def create_app(
    mock_mode: bool | None = None,
    update_manager: UpdateManager | None = None,
) -> Flask:
    """Lag Flask-appen. Funksjonsformen gjør appen enkel å teste."""

    if mock_mode is None:
        mock_mode = os.name == "nt" or os.getenv("PI_DISPLAY_MOCK") == "1"

    app = Flask(__name__)
    app.config["MOCK_MODE"] = mock_mode
    app.config["NODE_TOKEN"] = os.getenv("PI_DISPLAY_NODE_TOKEN", "")

    dashboard = DashboardState(mock_mode=mock_mode)
    updater = update_manager or UpdateManager()
    browser = BrowserTransport()
    esp32 = Esp32Transport(enabled=False)
    transports = TransportHub([browser, esp32])

    # Lagres i appen slik at testene (og vi senere) kan finne komponentene.
    app.extensions["dashboard"] = dashboard
    app.extensions["transports"] = transports
    app.extensions["updater"] = updater

    @app.get("/")
    def index() -> str:
        return render_template("index.html", mock_mode=mock_mode)

    @app.get("/api/health")
    def health() -> Any:
        return jsonify({"ok": True, "mock_mode": mock_mode})

    @app.get("/api/state")
    def get_state() -> Any:
        payload = dashboard.snapshot()
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

        payload = dashboard.snapshot()
        transports.publish(payload)
        return jsonify({"ok": True, "state": browser.latest()})

    @app.post("/api/demo/start")
    def start_demo() -> Any:
        body = request.get_json(silent=True) or {}
        iterations = body.get("iterations", 10_000_000)
        try:
            iterations = int(iterations)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "iterations må være et heltall"}), 400

        if not dashboard.start_demo(iterations):
            return jsonify({"ok": False, "error": "Beregningen kjører allerede"}), 409

        dashboard.set_screen("nerd")
        return jsonify({"ok": True, "message": "Monte Carlo-demo startet"}), 202

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
        try:
            node = dashboard.register_node(body, request.remote_addr)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        return jsonify({"ok": True, "node": node}), 202

    @app.get("/api/update/status")
    def update_status() -> Any:
        return jsonify(updater.status())

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
    parser = argparse.ArgumentParser(description="Pi Display Lab")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="bruk stabile eksempeldata (nyttig på Windows)",
    )
    parser.add_argument("--port", type=int, default=5000, help="HTTP-port (standard: 5000)")
    args = parser.parse_args()

    selected_app = create_app(mock_mode=True) if args.mock else app
    mode = "MOCK" if selected_app.config["MOCK_MODE"] else "PI / LIVE"
    print(f"Pi Display Lab starter i {mode}-modus")
    print(f"Åpne http://127.0.0.1:{args.port} på denne maskinen")
    print("Fra en annen PC: bruk Pi-ens IP-adresse i stedet for 127.0.0.1")
    selected_app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)
