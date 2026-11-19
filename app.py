"""HTTP-laget: ruter mellom nettleseren og prosjektets state/transport."""

from __future__ import annotations

import argparse
import base64
import math
import os
import secrets
from datetime import datetime
from typing import Any

from flask import Flask, Response, jsonify, request

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
from garmin_charts import LAP_LIMIT, ROUTE_LIMIT, activity_download_id
from transports import BrowserTransport, Esp32Transport, TransportHub
from updates import UpdateManager
from spotify import COMMANDS, TRACK_ID


DESKDISPLAY_NAME_MAX = 16


def _compact_text(value: Any, maximum_bytes: int, default: str = "-") -> str:
    """Return one safe tab-protocol field with a strict UTF-8 byte limit."""

    text = str(value or default).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
    text = text or default
    encoded = text.encode("utf-8")[:maximum_bytes]
    while encoded:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return default


def _tenths(value: Any) -> int:
    return int(round(float(value) * 10)) if isinstance(value, (int, float)) else 0


def _epoch(value: Any) -> int:
    if not isinstance(value, str):
        return 0
    try:
        return max(0, int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()))
    except ValueError:
        return 0


def _deskdisplay_state_lines(payload: dict[str, Any], worker_hosts: tuple[str, ...],
                             *, include_activities: bool = False, include_charts: bool = False,
                             include_laps: bool = False, include_media: bool = False,
                             cover: bytes = b"", include_library: bool = False,
                             include_targets: bool = False, include_maps: bool = False) -> str:
    """Render compact controller state for the local DeskDisplay gateway."""

    nodes = list(payload.get("nodes") or [])
    local = next((node for node in nodes if node.get("kind") == "local"), None)
    remote = [node for node in nodes if node.get("kind") != "local"]
    ordered: list[dict[str, Any]] = []
    if local is not None:
        ordered.append(local)

    def keys(node: dict[str, Any]) -> set[str]:
        values = {str(node.get("id") or "").casefold(), str(node.get("name") or "").casefold()}
        values.update(value.split(".", 1)[0] for value in tuple(values) if value)
        if node.get("ip"):
            values.add(str(node["ip"]).casefold())
        return values

    unused = list(remote)
    for host in worker_hosts:
        host_keys = {host.casefold(), host.split(".", 1)[0].casefold()}
        match = next((node for node in unused if keys(node) & host_keys), None)
        if match is not None:
            unused.remove(match)
            ordered.append(match)
        else:
            # Keep configured workers visible before their first heartbeat.
            ordered.append(
                {
                    "name": host.split(".", 1)[0],
                    "cpu": 0,
                    "temp": None,
                    "ram": 0,
                    "uptime_seconds": 0,
                    "online": False,
                }
            )
    # Do not truncate here. The controller gateway divides the complete list
    # into display-sized pages before encoding the secure frames.
    ordered.extend(unused)

    lines = ["DSSTATE/2"]
    for node in ordered:
        name = str(node.get("name") or node.get("id") or "node")
        name = name.replace("\t", " ").replace("\r", " ").replace("\n", " ")[:DESKDISPLAY_NAME_MAX]
        cpu = node.get("cpu")
        ram = node.get("ram")
        temp = node.get("temp")
        cpu_tenths = int(round(float(cpu) * 10)) if isinstance(cpu, (int, float)) else 0
        ram_tenths = int(round(float(ram) * 10)) if isinstance(ram, (int, float)) else 0
        temp_tenths = int(round(float(temp) * 10)) if isinstance(temp, (int, float)) else -32768
        uptime = int(node.get("uptime_seconds") or 0)
        online = 1 if node.get("online") else 0
        lines.append(f"node\t{name}\t{cpu_tenths}\t{temp_tenths}\t{ram_tenths}\t{uptime}\t{online}")

    training = payload.get("training") if isinstance(payload.get("training"), dict) else {}
    training_source = _compact_text(training.get("source"), 12, "none")
    lines.append(f"training\t{1 if training.get('available') else 0}\t{training_source}")
    workouts = []
    if isinstance(training.get("today"), dict):
        workouts.append((training["today"], 1))
    workouts.extend((item, 0) for item in list(training.get("upcoming") or [])[:7])
    for workout, is_today in workouts[:7]:
        lines.append(
            "\t".join(
                (
                    "workout",
                    _compact_text(workout.get("date"), 10),
                    _compact_text(workout.get("title"), 36, "Workout"),
                    _compact_text(workout.get("activity_type"), 14, "Workout"),
                    str(int(workout.get("duration_minutes") or 0)),
                    str(_tenths(workout.get("distance_km"))),
                    str(is_today),
                    _compact_text(workout.get("description"), 240, "-"),
                )
            )
        )
    activity = training.get("last_activity")
    if isinstance(activity, dict):
        lines.append("\t".join(("activity", _compact_text(activity.get("date"), 10),
                                _compact_text(activity.get("activity_type"), 14, "Activity"),
                                str(_tenths(activity.get("distance_km"))),
                                str(int(activity.get("duration_seconds") or 0)),
                                str(int(round(float(activity.get("average_pace_min_per_km") or 0) * 100))),
                                str(int(activity.get("average_hr") or 0)))))
    calendar = payload.get("calendar") if isinstance(payload.get("calendar"), dict) else {}
    calendar_source = _compact_text(calendar.get("source"), 12, "none")
    lines.append(f"calendar\t{1 if calendar.get('available') else 0}\t{calendar_source}")
    for event in list(calendar.get("events") or [])[:3]:
        if not isinstance(event, dict):
            continue
        lines.append(
            "\t".join(
                (
                    "event",
                    str(_epoch(event.get("start"))),
                    str(_epoch(event.get("end"))),
                    "1" if event.get("all_day") else "0",
                    _compact_text(event.get("title"), 40, "Calendar event"),
                    _compact_text(event.get("location"), 24),
                )
            )
        )
    spotify = payload.get("spotify") or {}
    statuses = {"not_configured": 0, "playing": 1, "paused": 2, "no_device": 3,
                "reauthorize": 4, "unauthorized": 4, "forbidden": 5, "rate_limited": 6, "unavailable": 7}
    flags = (int(bool(spotify.get("can_control")))
             | int(bool(spotify.get("can_next"))) << 1
             | int(bool(spotify.get("can_previous"))) << 2
             | int(bool(spotify.get("pending"))) << 3)
    lines.append("\t".join(("spotify", str(statuses.get(spotify.get("status"), 7)),
                            str(flags), str(int(spotify.get("progress_ms") or 0)),
                            str(int(spotify.get("duration_ms") or 0)),
                            _compact_text(spotify.get("title"), 96),
                            _compact_text(spotify.get("artist"), 96),
                            _compact_text(spotify.get("device"), 48))))
    track_id = spotify.get("track_id")
    if include_media and isinstance(track_id, str) and TRACK_ID.fullmatch(track_id):
        lines.append("spotify_track\t" + track_id)
        if include_library and spotify.get("library") in (1, 2, 3, 4, 5):
            lines.append(f"spotify_library\t{spotify['library']}")
        if cover:
            lines.append("spotify_cover\t" + base64.b64encode(cover).decode("ascii"))
    garmin = payload.get("garmin") or {}
    garmin_status = {"not_configured": 0, "ok": 1, "stale": 2, "auth_error": 3, "error": 4}
    lines.append(f"garmin\t{garmin_status.get(garmin.get('status'), 4)}\t{int(garmin.get('updated_at') or 0)}")
    if include_charts:
        lines.append(f"garmin_history_end\t{garmin.get('history_end', 0)}")
    for group in list(garmin.get("groups") or [])[:4]:
        lines.append("garmin_group\t" + _compact_text(group.get("title"), 20, "Garmin"))
        for metric in list(group.get("metrics") or [])[:6]:
            history = []
            values = list(metric.get("history") or [])[:7]
            # Sparklines have no numeric axis. Scale large counts together so
            # daily steps retain their shape within the compact signed range.
            peak = max([abs(v) for v in values if isinstance(v, (float, int))
                        and not isinstance(v, bool) and math.isfinite(v)] or [0])
            divisor = max(1, math.ceil(peak / 3000)) if include_charts else max(1, peak / 3000)
            for value in values:
                valid = (isinstance(value, (float, int)) and not isinstance(value, bool)
                         and math.isfinite(value))
                history.append(str(int(round(value / divisor * 10))) if valid else "-32768")
            history.extend(["-32768"] * (7 - len(history)))
            fields = ("garmin_metric", _compact_text(metric.get("label"), 20),
                      _compact_text(metric.get("value"), 16, "--"),
                      _compact_text(metric.get("unit"), 12), ",".join(history))
            lines.append("\t".join(fields + (str(divisor),) if include_charts else fields))
    activities = garmin.get("activities")
    if include_activities and isinstance(activities, list):
        for activity in activities[:10]:
            if not isinstance(activity, dict):
                continue
            values = activity.get("values")
            if not isinstance(values, list) or len(values) != 6:
                continue
            lines.append("\t".join(("garmin_activity", _compact_text(activity.get("date"), 10),
                                    _compact_text(activity.get("title"), 48, "Activity"),
                                    _compact_text(activity.get("kind"), 24),
                                    *(_compact_text(value, 16, "--") for value in values))))
            map_id = activity_download_id(activity.get("map_id"))
            if include_maps and map_id:
                lines.append(f"garmin_activity_id\t{map_id}")
            charts = activity.get("charts")
            if include_charts and isinstance(charts, list):
                for index, series in enumerate(charts[:5 if include_media else 3]):
                    if isinstance(series, list) and len(series) == 24:
                        samples = ",".join(str(value) if type(value) is int and -32768 <= value <= 32767
                                           else "-32768" for value in series)
                        lines.append(f"garmin_chart\t{index}\t{samples}")
            laps = activity.get("laps")
            total = activity.get("lap_total")
            if include_laps and isinstance(laps, list) and type(total) is int and 0 < total <= 65535:
                lines.append(f"garmin_lap_total\t{total}")
                for lap in laps[:min(total, LAP_LIMIT)]:
                    if (isinstance(lap, list) and len(lap) == 3
                        and all(type(value) is int and 0 <= value <= limit
                                for value, limit in zip(lap, (0xFFFFFFFF, 0xFFFFFFFF, 255)))):
                        lines.append("\t".join(("garmin_lap", *map(str, lap))))
            route = activity.get("route")
            if include_media and isinstance(route, list):
                points = [bytes(point).hex() for point in route[:ROUTE_LIMIT]
                          if isinstance(point, list) and len(point) == 2
                          and all(type(value) is int and 0 <= value <= 240 for value in point)]
                if len(points) >= 2:
                    lines.append("garmin_route\t" + "".join(points))
            target = activity.get("pace_target")
            if (include_targets and isinstance(target, list) and len(target) == 2
                and all(type(value) is int and 0 < value <= 32767 for value in target)
                and target[0] <= target[1]):
                lines.append(f"garmin_pace_target\t{target[0]}\t{target[1]}")
    return "\n".join(lines) + "\n"


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

    # The controller serves an API for workers and the secure display gateway,
    # not a browser UI. Disable Flask's implicit /static route as well.
    app = Flask(__name__, static_folder=None)
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

    @app.get("/api/health")
    def health() -> Any:
        return jsonify({"ok": True, "mock_mode": mock_mode})

    @app.get("/api/state")
    def get_state() -> Any:
        payload = dashboard.snapshot(cluster_status=cluster_status.snapshot())
        garmin = payload.get("garmin")
        if isinstance(garmin, dict):
            payload["garmin"] = {key: value for key, value in garmin.items() if key != "activities"}
        transports.publish(payload)
        return jsonify(browser.latest())

    @app.get("/api/deskdisplay/state")
    def deskdisplay_state() -> Any:
        """Expose compact display state only to the local secure gateway."""

        if request.remote_addr not in {"127.0.0.1", "::1"}:
            return jsonify({"ok": False, "error": "Kun lokal gateway er tillatt"}), 403
        payload = dashboard.snapshot(cluster_status=cluster_status.snapshot())
        include_media = request.headers.get("X-DeskDisplay-Media") == "1"
        track_id = (payload.get("spotify") or {}).get("track_id")
        cover = dashboard.spotify_provider.cover_for_track(track_id) if include_media and track_id else b""
        return Response(
            _deskdisplay_state_lines(payload, settings.worker_hosts,
                                     include_activities=request.headers.get("X-DeskDisplay-Activities") == "1",
                                     include_charts=request.headers.get("X-DeskDisplay-Charts") == "1",
                                     include_laps=request.headers.get("X-DeskDisplay-Laps") == "1",
                                     include_media=include_media, cover=cover,
                                     include_library=request.headers.get("X-DeskDisplay-Library") == "1",
                                     include_targets=request.headers.get("X-DeskDisplay-Targets") == "1",
                                     include_maps=request.headers.get("X-DeskDisplay-Maps") == "1"),
            mimetype="text/plain",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/deskdisplay/garmin/map/<activity_id>")
    def deskdisplay_map(activity_id: str) -> Any:
        headers = {"Cache-Control": "no-store"}
        if (request.remote_addr not in {"127.0.0.1", "::1"}
                or request.host.split(":", 1)[0] != "127.0.0.1"
                or request.headers.get("Origin")
                or request.headers.get("X-DeskDisplay-Maps") != "1"):
            return Response(status=403, headers=headers)
        map_id = activity_download_id(activity_id)
        if map_id is None:
            return Response(status=404, headers=headers)
        try:
            image = dashboard.garmin_provider.map_image(map_id)
        except ImportError:
            image = b""
        if not image or len(image) > 24576:
            return Response(status=404, headers=headers)
        return Response(image, mimetype="image/jpeg", headers=headers)

    @app.post("/api/deskdisplay/spotify/command")
    def spotify_command() -> Any:
        # JSON-only prevents browser form posts; numeric Host prevents DNS rebinding.
        if (request.remote_addr not in {"127.0.0.1", "::1"}
                or request.host.split(":", 1)[0] != "127.0.0.1"
                or not request.is_json or request.headers.get("Origin")):
            return jsonify({"ok": False}), 403
        body = request.get_json(silent=True)
        action = body.get("action") if isinstance(body, dict) else None
        if action == "save":
            track_id = body.get("track_id")
            if not isinstance(track_id, str) or not TRACK_ID.fullmatch(track_id):
                return jsonify({"ok": False}), 400
            accepted = dashboard.spotify_provider.save_track(track_id)
        elif isinstance(action, str) and action in COMMANDS:
            accepted = dashboard.spotify_provider.command(action)
        else:
            return jsonify({"ok": False}), 400
        return jsonify({"ok": accepted}), 202 if accepted else 409

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
    print(f"API tilgjengelig på http://127.0.0.1:{args.port}/api/health")
    selected_app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)
