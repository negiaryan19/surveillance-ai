"""Project Chanakya HTTP API.

``create_app(engine)`` builds the Flask app around a duck-typed engine so the
routes can be tested with fakes; ``main()`` wires the real engine. Security
decisions worth knowing:

* Auth is optional (``CHANAKYA_API_TOKEN``). When it is unset the server only
  accepts loopback ``Host`` headers (DNS-rebinding guard) and ``main()``
  refuses to bind to a non-loopback address.
* CORS preflights (OPTIONS) are exempt from auth: they never carry
  credentials, and a 401 preflight makes every browser fetch fail.
* Mutating requests with a foreign ``Origin`` are rejected in BOTH modes: a
  cross-site multipart POST is not preflighted, so without this any web page
  could enroll an "authorized" face or pause alerts.
* ``?token=`` exists because ``<img>``/``<video>``/``EventSource`` cannot set
  headers; the access log is filtered so the token never reaches disk.
* Exception text never reaches a client (the 500 body is fixed).
"""

from __future__ import annotations

import hmac
import io
import json
import logging
import re
import sys
import threading
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory  # noqa: E402
from flask_cors import CORS  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

from config import settings as default_settings  # noqa: E402
from src.report_generator import generate_pdf_report  # noqa: E402
from src.security_vault import encrypt_bytes  # noqa: E402

log = logging.getLogger("chanakya.api")

AUTH_EXEMPT_ENDPOINTS = frozenset({"health", "index", "frontend_asset"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
MAX_SSE_SUBSCRIBERS = 32
MAX_MJPEG_VIEWERS = 8
SSE_PING_SECONDS = 15.0
ALLOWED_FACE_EXTENSIONS = frozenset({"jpg", "jpeg", "png"})
MAX_FACE_UPLOAD = 5 * 1024 * 1024
_TOKEN_RE = re.compile(r"(token=)[^&\s\"']+")


class _TokenRedactor(logging.Filter):
    """Werkzeug logs the full query string; strip ``?token=`` before it hits a file."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _TOKEN_RE.sub(r"\1***", record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(_TOKEN_RE.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {
                    k: (_TOKEN_RE.sub(r"\1***", v) if isinstance(v, str) else v) for k, v in record.args.items()
                }
        return True


def _json_error(status: int, message: str):
    return jsonify({"error": message}), status


def _hostname(host: str | None) -> str:
    """``Host`` header without the port: ``127.0.0.1:5001`` -> ``127.0.0.1``, ``[::1]:5001`` -> ``[::1]``."""
    host = (host or "").strip().lower()
    if host.startswith("["):
        return host.split("]", 1)[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


def _parse_bool(value: str | None):
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    raise ValueError("expected true or false")


def _parse_int(value: str | None, name: str, lo: int | None = None, hi: int | None = None, default=None):
    if value is None or value == "":
        return default
    try:
        n = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if lo is not None and n < lo:
        raise ValueError(f"{name} must be >= {lo}")
    if hi is not None and n > hi:
        raise ValueError(f"{name} must be <= {hi}")
    return n


def create_app(engine, settings=None) -> Flask:
    if engine is None:
        raise ValueError("create_app requires an engine")
    s = settings or default_settings
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
    app.config["JSON_SORT_KEYS"] = False
    CORS(app, origins=list(s.CORS_ORIGINS))
    logging.getLogger("werkzeug").addFilter(_TokenRedactor())

    token = s.API_TOKEN or None
    token_bytes = token.encode("utf-8") if token else None
    started = time.time()
    frontend_dist = Path(s.FRONTEND_DIST)
    sse_count = [0]
    viewers: dict[str, int] = {}
    counters_lock = threading.Lock()

    # ------------------------------------------------------------------ guards
    def _supplied_token() -> str | None:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header[7:].strip()
        return request.args.get("token")

    def _origin_allowed(origin: str) -> bool:
        if origin in s.CORS_ORIGINS or "*" in s.CORS_ORIGINS:
            return True
        return origin == request.host_url.rstrip("/")

    @app.before_request
    def _guard():
        if request.method == "OPTIONS":
            return None  # preflights carry no credentials; flask-cors answers them
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = request.headers.get("Origin")
            if origin and not _origin_allowed(origin):
                return _json_error(403, "forbidden origin")
        if token_bytes is None:
            if _hostname(request.host) not in LOOPBACK_HOSTS:
                return _json_error(403, "forbidden host")
            return None
        if request.endpoint in AUTH_EXEMPT_ENDPOINTS:
            return None
        supplied = _supplied_token()
        if supplied is None or not hmac.compare_digest(supplied.encode("utf-8"), token_bytes):
            return _json_error(401, "unauthorized")
        return None

    # ------------------------------------------------------------------ errors
    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        message = {
            400: "bad request",
            401: "unauthorized",
            403: "forbidden",
            404: "not found",
            405: "method not allowed",
            413: "payload too large",
            415: "unsupported media type",
            503: "service unavailable",
        }.get(exc.code, exc.name.lower())
        if exc.code in (400, 404, 413, 503) and exc.description and exc.description != exc.__class__.description:
            message = exc.description
        return _json_error(exc.code or 500, message)

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        log.exception("unhandled error on %s", request.endpoint)
        return _json_error(500, "internal error")

    # ------------------------------------------------------------------ helpers
    def _worker_or_404(camera_id: str):
        worker = engine.get_worker(camera_id)
        if worker is None:
            abort(404, description="unknown camera")
        return worker

    def _incident_or_404(incident_id: int) -> dict:
        incident = engine.db.get_incident(incident_id)
        if incident is None:
            abort(404, description="unknown incident")
        return incident

    def _serve_incident_file(incident_id: int, key: str, root, mimetype: str, ext: str):
        incident = _incident_or_404(incident_id)
        path = s.safe_child(incident.get(key), root)
        if path is None:
            abort(404, description="file not available")
        as_attachment = request.args.get("download") == "1"
        return send_file(
            path,
            mimetype=mimetype,
            conditional=True,
            as_attachment=as_attachment,
            download_name=f"incident_{incident_id}.{ext}",
        )

    def _json_object():
        body = request.get_json(silent=True)
        return body if isinstance(body, dict) else None

    # ------------------------------------------------------------------ meta
    @app.get("/api/health", endpoint="health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "version": s.VERSION,
                "auth_required": token_bytes is not None,
                "uptime_s": int(time.time() - started),
            }
        )

    @app.get("/api/modules")
    def modules():
        return jsonify(engine.modules())

    # ------------------------------------------------------------------ cameras & streams
    @app.get("/api/cameras")
    def cameras():
        out = []
        for status in engine.cameras():
            cid = status["id"]
            out.append(
                {**status, "stream_url": f"/video_feed/{cid}", "snapshot_url": f"/api/cameras/{cid}/snapshot.jpg"}
            )
        return jsonify(out)

    def _mjpeg(worker, camera_id: str):
        with counters_lock:
            if viewers.get(camera_id, 0) >= MAX_MJPEG_VIEWERS:
                abort(503, description="too many streams")
            viewers[camera_id] = viewers.get(camera_id, 0) + 1

        def generate():
            seq = -1
            try:
                while True:
                    seq, jpeg = worker.wait_for_frame(seq, timeout=1.0)
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(jpeg)).encode()
                        + b"\r\n\r\n"
                        + jpeg
                        + b"\r\n"
                    )
            finally:
                with counters_lock:
                    viewers[camera_id] = max(0, viewers.get(camera_id, 1) - 1)

        return Response(
            generate(), mimetype="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store"}
        )

    @app.get("/video_feed/<camera_id>")
    def video_feed(camera_id: str):
        return _mjpeg(_worker_or_404(camera_id), camera_id)

    def _legacy_feed(index: int):
        ids = engine.camera_ids()
        if index >= len(ids):
            abort(404, description="no such camera")
        return _mjpeg(_worker_or_404(ids[index]), ids[index])

    @app.get("/video_feed_1")
    def video_feed_1():
        return _legacy_feed(0)

    @app.get("/video_feed_2")
    def video_feed_2():
        return _legacy_feed(1)

    @app.get("/api/cameras/<camera_id>/snapshot.jpg")
    def camera_snapshot(camera_id: str):
        worker = _worker_or_404(camera_id)
        jpeg = worker.latest_jpeg(annotated=request.args.get("raw") != "1")
        return Response(jpeg, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------------ incidents
    @app.get("/api/incidents")
    def incidents():
        try:
            limit = _parse_int(request.args.get("limit"), "limit", 1, 200, default=50)
            offset = _parse_int(request.args.get("offset"), "offset", 0, None, default=0)
            min_threat = _parse_int(request.args.get("min_threat"), "min_threat", 0, 100)
            acknowledged = _parse_bool(request.args.get("acknowledged"))
        except ValueError as exc:
            return _json_error(400, str(exc))
        zone = request.args.get("zone") or None
        camera = request.args.get("camera") or None
        since = request.args.get("since") or None
        try:
            items, total = engine.db.list_incidents(
                limit=limit,
                offset=offset,
                min_threat=min_threat,
                zone=zone,
                camera=camera,
                since=since,
                acknowledged=acknowledged,
            )
        except ValueError as exc:
            return _json_error(400, str(exc))
        return jsonify(
            {"items": [engine.serialize_incident(i) for i in items], "total": total, "limit": limit, "offset": offset}
        )

    @app.get("/api/incidents/<int:incident_id>")
    def incident(incident_id: int):
        return jsonify(engine.serialize_incident(_incident_or_404(incident_id)))

    @app.get("/api/incidents/<int:incident_id>/snapshot")
    def incident_snapshot(incident_id: int):
        return _serve_incident_file(incident_id, "image_path", s.SNAPSHOTS_DIR, "image/jpeg", "jpg")

    @app.get("/api/incidents/<int:incident_id>/clip")
    def incident_clip(incident_id: int):
        return _serve_incident_file(incident_id, "clip_path", s.VIDEOS_DIR, "video/mp4", "mp4")

    @app.post("/api/incidents/<int:incident_id>/ack")
    def incident_ack(incident_id: int):
        body = _json_object() or {}
        acknowledged = body.get("acknowledged", True)
        if not isinstance(acknowledged, bool):
            return _json_error(400, "acknowledged must be a boolean")
        if not engine.db.acknowledge(incident_id, acknowledged):
            abort(404, description="unknown incident")
        engine.event_bus.publish("ack", {"id": incident_id, "acknowledged": acknowledged})
        return jsonify(engine.serialize_incident(engine.db.get_incident(incident_id)))

    @app.get("/api/logs")
    def legacy_logs():
        rows = engine.db.get_recent_logs(limit=15)
        return jsonify([{"timestamp": r[0], "object": r[1], "threat": r[2], "zone": r[3]} for r in rows])

    @app.get("/api/stats")
    def stats():
        try:
            hours = _parse_int(request.args.get("hours"), "hours", 1, 168, default=24)
        except ValueError as exc:
            return _json_error(400, str(exc))
        return jsonify(engine.db.stats(hours=hours))

    # ------------------------------------------------------------------ zones
    @app.get("/api/zones")
    def zones():
        from src.zones import LEVELS

        return jsonify({"levels": list(LEVELS), "zones": engine.zone_manager.to_dict()})

    @app.put("/api/zones/<camera_id>")
    def put_zones(camera_id: str):
        if camera_id != "default" and camera_id not in engine.camera_ids():
            abort(404, description="unknown camera")
        body = _json_object()
        if body is None or not isinstance(body.get("zones"), list):
            return _json_error(400, "expected a JSON object with a zones list")
        try:
            saved = engine.zone_manager.set_zones(camera_id, body["zones"])
        except ValueError as exc:
            return _json_error(400, str(exc))
        engine.event_bus.publish("zones", {"camera_id": camera_id})
        return jsonify({"camera_id": camera_id, "zones": [z.to_dict() for z in saved]})

    # ------------------------------------------------------------------ alerts
    @app.get("/api/alerts")
    def alerts():
        return jsonify({"paused": bool(engine.alert_manager.is_paused())})

    def _set_paused(paused: bool):
        (engine.alert_manager.pause if paused else engine.alert_manager.resume)()
        engine.event_bus.publish("status", engine.status_snapshot())
        return jsonify({"paused": bool(engine.alert_manager.is_paused())})

    @app.post("/api/alerts/pause")
    def alerts_pause():
        return _set_paused(True)

    @app.post("/api/alerts/resume")
    def alerts_resume():
        return _set_paused(False)

    # ------------------------------------------------------------------ faces
    @app.get("/api/faces")
    def faces():
        return jsonify({"people": engine.face_recognizer.list_people()})

    @app.post("/api/faces")
    def enroll_face():
        name = (request.form.get("name") or "").strip()
        upload = request.files.get("image")
        if not name or upload is None or not upload.filename:
            return _json_error(400, "name and image are required")
        ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
        if ext not in ALLOWED_FACE_EXTENSIONS:
            return _json_error(400, "image must be a .jpg, .jpeg or .png file")
        data = upload.read(MAX_FACE_UPLOAD + 1)
        if len(data) > MAX_FACE_UPLOAD:
            return _json_error(400, "image larger than 5 MB")
        try:
            result = engine.face_recognizer.enroll(name, data)
        except ValueError as exc:
            return _json_error(400, str(exc))
        engine.event_bus.publish("faces", {"count": len(engine.face_recognizer.known_names)})
        return jsonify(result), 201

    @app.delete("/api/faces/<name>")
    def remove_face(name: str):
        if not engine.face_recognizer.remove(name):
            abort(404, description="unknown person")
        engine.event_bus.publish("faces", {"count": len(engine.face_recognizer.known_names)})
        return jsonify({"removed": True})

    # ------------------------------------------------------------------ events (SSE)
    @app.get("/api/events")
    def events():
        with counters_lock:
            if sse_count[0] >= MAX_SSE_SUBSCRIBERS:
                abort(503, description="too many event streams")
            sse_count[0] += 1
        subscription = engine.event_bus.subscribe()

        def frame(event_type: str, data) -> str:
            return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

        def generate():
            try:
                yield frame("status", engine.status_snapshot())
                last_ping = time.monotonic()
                while True:
                    item = subscription.get(timeout=1.0)
                    if item is not None:
                        yield frame(item[0], item[1])
                    if time.monotonic() - last_ping >= SSE_PING_SECONDS:
                        last_ping = time.monotonic()
                        yield ": ping\n\n"
            finally:
                subscription.close()
                with counters_lock:
                    sse_count[0] = max(0, sse_count[0] - 1)

        return Response(
            generate(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    # ------------------------------------------------------------------ reports
    def _report_response(encrypted: bool):
        path = generate_pdf_report(engine.db, out_dir=s.REPORTS_DIR, tz_name=s.LOCAL_TZ)
        if not encrypted:
            return send_file(path, mimetype="application/pdf", as_attachment=True, download_name=path.name)
        blob = encrypt_bytes(path.read_bytes(), key_file=s.KEY_FILE)
        return send_file(
            io.BytesIO(blob), mimetype="application/octet-stream", as_attachment=True, download_name=path.name + ".enc"
        )

    @app.get("/api/report.pdf")
    def report():
        return _report_response(request.args.get("encrypted") == "1")

    @app.get("/download_secure_report")
    def legacy_report():
        return _report_response(False)

    # ------------------------------------------------------------------ frontend
    @app.get("/", endpoint="index")
    def index():
        if (frontend_dist / "index.html").is_file():
            return send_from_directory(frontend_dist, "index.html")
        return jsonify({"name": "Project Chanakya API", "version": s.VERSION})

    @app.get("/assets/<path:filename>", endpoint="frontend_asset")
    @app.get("/favicon.svg", endpoint="frontend_asset", defaults={"filename": ""})
    def frontend_asset(filename: str):
        if filename:
            return send_from_directory(frontend_dist / "assets", filename)
        return send_from_directory(frontend_dist, "favicon.svg")

    return app


def main() -> int:
    s = default_settings
    logging.basicConfig(
        level=logging.DEBUG if s.DEBUG else logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    if s.API_TOKEN is None and s.HOST not in LOOPBACK_HOSTS:
        log.error("refusing to bind %s without CHANAKYA_API_TOKEN: open mode is loopback-only", s.HOST)
        return 2
    if s.API_TOKEN is not None and len(s.API_TOKEN) < 16:
        log.warning("CHANAKYA_API_TOKEN is shorter than 16 characters")

    from src.engine.engine import SurveillanceEngine

    s.ensure_dirs()
    engine = SurveillanceEngine(s)
    app = create_app(engine, s)
    engine.start()
    import atexit

    atexit.register(engine.stop)
    log.info(
        "Project Chanakya v%s on http://%s:%s (auth %s)",
        s.VERSION,
        s.HOST,
        s.PORT,
        "required" if s.API_TOKEN else "off, loopback only",
    )
    app.run(host=s.HOST, port=s.PORT, debug=False, use_reloader=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
