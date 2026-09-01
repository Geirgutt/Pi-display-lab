"""Separat Flask-app som deler ut og registrerer cluster-jobber."""

from __future__ import annotations

import argparse
from typing import Any

from flask import Flask, jsonify, request

from cluster_auth import ClusterCredentials, bearer_token, load_cluster_credentials
from cluster_jobs import ClusterJobQueue
from config import AppConfig, load_config


def create_coordinator_app(
    job_queue: ClusterJobQueue | None = None,
    credentials: ClusterCredentials | None = None,
    settings: AppConfig | None = None,
) -> Flask:
    app = Flask(__name__)
    queue = job_queue or ClusterJobQueue()
    settings = settings or load_config()
    credentials = credentials or load_cluster_credentials(
        settings.cluster.credentials_file
    )
    app.extensions["cluster_job_queue"] = queue

    def unauthorized() -> tuple[Any, int, dict[str, str]]:
        return (
            jsonify({"ok": False, "error": "Ugyldig eller manglende credential"}),
            401,
            {"WWW-Authenticate": "Bearer"},
        )

    def admin_is_authenticated() -> bool:
        return credentials.authenticate_admin(
            bearer_token(request.headers.get("Authorization"))
        )

    def authenticated_worker() -> str:
        worker = request.headers.get("X-Worker-ID", "")
        token = bearer_token(request.headers.get("Authorization"))
        return worker if credentials.authenticate_worker(worker, token) else ""

    @app.get("/health")
    def health() -> Any:
        return jsonify({"ok": True, "service": "cluster-coordinator"})

    @app.get("/job")
    def get_job() -> Any:
        worker = authenticated_worker()
        if not worker:
            return unauthorized()
        try:
            job = queue.claim(worker)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        if job is None:
            return "", 204
        return jsonify(job)

    @app.post("/result")
    def post_result() -> Any:
        worker = authenticated_worker()
        if not worker:
            return unauthorized()
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "Forventet et JSON-objekt"}), 400
        if body.get("worker") != worker:
            return jsonify({"ok": False, "error": "Worker-identiteten samsvarer ikke"}), 403
        try:
            result = queue.record_result(body)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        return jsonify({"ok": True, "result": result}), 202

    @app.get("/status")
    def status() -> Any:
        if not admin_is_authenticated():
            return unauthorized()
        return jsonify(queue.status())

    @app.post("/jobs")
    def create_jobs() -> Any:
        if not admin_is_authenticated():
            return unauthorized()
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
