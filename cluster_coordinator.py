"""Separat Flask-app som deler ut og registrerer cluster-jobber."""

from __future__ import annotations

import argparse
from typing import Any

from flask import Flask, jsonify, request

from cluster_jobs import ClusterJobQueue
from config import load_config


def create_coordinator_app(job_queue: ClusterJobQueue | None = None) -> Flask:
    app = Flask(__name__)
    queue = job_queue or ClusterJobQueue()
    app.extensions["cluster_job_queue"] = queue

    @app.get("/health")
    def health() -> Any:
        return jsonify({"ok": True, "service": "cluster-coordinator"})

    @app.get("/job")
    def get_job() -> Any:
        worker = request.args.get("worker") or request.remote_addr or "unknown"
        try:
            job = queue.claim(worker)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        if job is None:
            return "", 204
        return jsonify(job)

    @app.post("/result")
    def post_result() -> Any:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "Forventet et JSON-objekt"}), 400
        try:
            result = queue.record_result(body)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        return jsonify({"ok": True, "result": result}), 202

    @app.get("/status")
    def status() -> Any:
        return jsonify(queue.status())

    @app.post("/jobs")
    def create_jobs() -> Any:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "Forventet et JSON-objekt"}), 400
        try:
            job_ids = queue.enqueue_prime_range(body)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        return jsonify({"ok": True, "created": len(job_ids), "job_ids": job_ids}), 201

    return app


app = create_coordinator_app()


if __name__ == "__main__":
    settings = load_config()
    parser = argparse.ArgumentParser(description="Pi Display Lab cluster coordinator")
    parser.add_argument("--port", type=int, default=settings.coordinator_port)
    args = parser.parse_args()
    print(f"Cluster coordinator lytter på port {args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)
