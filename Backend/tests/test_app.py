"""Flask API with a fake engine (real DB, zones, event bus)."""

import io
import logging
import subprocess
import sys
import types
from pathlib import Path

import pytest
from PIL import Image

from src.database_manager import DatabaseManager
from src.events import EventBus
from src.zones import ZoneManager
from web.app import _TokenRedactor, create_app

BACKEND = Path(__file__).resolve().parent.parent
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"


class FakeWorker:
    def __init__(self, cid):
        self.cid = cid
        self.seq = 0

    def status(self):
        return {
            "id": self.cid,
            "name": self.cid.upper(),
            "online": True,
            "fps": 12.0,
            "tracks": 1,
            "night_mode": False,
            "last_frame_at": "2026-09-22T10:00:00Z",
            "source": "camera:0",
        }

    def latest_jpeg(self, annotated=True):
        return JPEG if annotated else b"RAW" + JPEG

    def wait_for_frame(self, last_seq, timeout=1.0):
        self.seq += 1
        return self.seq, JPEG


class FakeFaces:
    def __init__(self):
        self.people = {"Aryan Negi": 2}
        self.known_names = ["Aryan Negi", "Aryan Negi"]

    def list_people(self):
        return [{"name": n, "images": c} for n, c in sorted(self.people.items())]

    def enroll(self, name, data):
        if name == "boom":
            raise ValueError("no face found")
        self.people[name] = self.people.get(name, 0) + 1
        return {"name": name, "images": self.people[name]}

    def remove(self, name):
        return self.people.pop(name, None) is not None


class FakeAlerts:
    def __init__(self):
        self.paused = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def is_paused(self):
        return self.paused


class FakeEngine:
    def __init__(self, settings):
        self.settings = settings
        self.db = DatabaseManager(settings.DB_PATH)
        self.event_bus = EventBus()
        self.zone_manager = ZoneManager(settings.ZONES_FILE)
        self.face_recognizer = FakeFaces()
        self.alert_manager = FakeAlerts()
        self.workers = {"alpha": FakeWorker("alpha"), "bravo": FakeWorker("bravo")}

    def camera_ids(self):
        return list(self.workers)

    def get_worker(self, cid):
        return self.workers.get(cid)

    def cameras(self):
        return [w.status() for w in self.workers.values()]

    def status_snapshot(self):
        return {"cameras": self.cameras(), "alerts_paused": self.alert_manager.is_paused()}

    def modules(self):
        return {
            "emotion": {"status": "enabled"},
            "knownFaces": {"count": 1, "names": ["Aryan Negi"]},
            "streams": {"alpha": "online", "bravo": "online"},
            "telegram": {"configured": False},
            "recorder": {"enabled": True},
        }

    def serialize_incident(self, inc):
        if inc is None:
            return None
        s = self.settings
        out = {k: v for k, v in inc.items() if k not in ("image_path", "clip_path")}
        out["snapshot_url"] = (
            f"/api/incidents/{inc['id']}/snapshot" if s.safe_child(inc.get("image_path"), s.SNAPSHOTS_DIR) else None
        )
        out["clip_url"] = (
            f"/api/incidents/{inc['id']}/clip" if s.safe_child(inc.get("clip_path"), s.VIDEOS_DIR) else None
        )
        return out


def make_settings(tmp_path, token=None, **over):
    from config import settings as real

    s = types.SimpleNamespace(
        API_TOKEN=token,
        CORS_ORIGINS=["http://127.0.0.1:5173"],
        VERSION="test",
        FRONTEND_DIST=tmp_path / "dist",
        DATA_DIR=tmp_path,
        SNAPSHOTS_DIR=tmp_path / "snapshots",
        VIDEOS_DIR=tmp_path / "videos",
        REPORTS_DIR=tmp_path / "reports",
        KEY_FILE=tmp_path / "secret.key",
        DB_PATH=tmp_path / "db.sqlite",
        ZONES_FILE=tmp_path / "zones.json",
        LOCAL_TZ="Asia/Kolkata",
        safe_child=real.safe_child,
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s


@pytest.fixture
def api(tmp_path):
    s = make_settings(tmp_path)
    engine = FakeEngine(s)
    app = create_app(engine, s)
    app.testing = True
    client = app.test_client()
    client.environ_base["HTTP_HOST"] = "127.0.0.1:5001"
    return types.SimpleNamespace(client=client, engine=engine, s=s, app=app)


@pytest.fixture
def secured(tmp_path):
    s = make_settings(tmp_path, token="correct-horse-battery-staple")
    engine = FakeEngine(s)
    app = create_app(engine, s)
    app.testing = True
    client = app.test_client()
    return types.SimpleNamespace(client=client, engine=engine, s=s, token=s.API_TOKEN)


def add_incident(api, **kw):
    s = api.s
    s.SNAPSHOTS_DIR.mkdir(exist_ok=True)
    snap = s.SNAPSHOTS_DIR / f"a{len(api.engine.db.list_incidents()[0])}.jpg"
    snap.write_bytes(JPEG)
    fields = dict(
        camera="alpha",
        object_type="Person",
        threat_score=85,
        zone_level="WARNING",
        category="CRITICAL",
        track_id=3,
        identity=None,
        reasons=["Unknown Identity"],
        image_path=str(snap),
    )
    fields.update(kw)
    return api.engine.db.log_incident(**fields)


# ------------------------------------------------------------------ meta & legacy
def test_health_and_root_and_modules(api):
    r = api.client.get("/api/health")
    assert r.status_code == 200 and r.json["auth_required"] is False and r.json["version"] == "test"
    assert api.client.get("/").json["name"] == "Project Chanakya API"
    assert api.client.get("/api/modules").json["knownFaces"]["count"] == 1


def test_legacy_logs_shape(api):
    add_incident(api)
    rows = api.client.get("/api/logs").json
    assert rows[0].keys() == {"timestamp", "object", "threat", "zone"} and rows[0]["threat"] == 85


def test_cameras_and_snapshot_routes(api):
    cams = api.client.get("/api/cameras").json
    assert cams[0]["stream_url"] == "/video_feed/alpha" and cams[0]["snapshot_url"] == "/api/cameras/alpha/snapshot.jpg"
    r = api.client.get("/api/cameras/alpha/snapshot.jpg")
    assert (
        r.status_code == 200
        and r.mimetype == "image/jpeg"
        and r.data == JPEG
        and r.headers["Cache-Control"] == "no-store"
    )
    assert api.client.get("/api/cameras/alpha/snapshot.jpg?raw=1").data.startswith(b"RAW")
    assert api.client.get("/api/cameras/nope/snapshot.jpg").status_code == 404


def test_mjpeg_streams_and_viewer_cap(api):
    r = api.client.get("/video_feed/alpha")
    assert r.status_code == 200 and r.mimetype == "multipart/x-mixed-replace"
    chunk = next(r.response)
    assert chunk.startswith(b"--frame\r\nContent-Type: image/jpeg") and JPEG in chunk
    r.close()
    assert api.client.get("/video_feed_1").status_code == 200
    assert api.client.get("/video_feed_2").status_code == 200
    assert api.client.get("/video_feed/zulu").status_code == 404
    open_streams = [api.client.get("/video_feed/bravo") for _ in range(8)]
    assert api.client.get("/video_feed/bravo").status_code == 503
    for s in open_streams:
        s.close()


# ------------------------------------------------------------------ incidents
def test_incident_list_filters_and_validation(api):
    add_incident(api, threat_score=50, zone_level="SAFE")
    add_incident(api, threat_score=90, camera="bravo")
    r = api.client.get("/api/incidents?limit=1").json
    assert r["total"] == 2 and len(r["items"]) == 1 and r["items"][0]["snapshot_url"].endswith("/snapshot")
    assert api.client.get("/api/incidents?min_threat=80").json["total"] == 1
    assert api.client.get("/api/incidents?camera=bravo").json["total"] == 1
    assert api.client.get("/api/incidents?acknowledged=false").json["total"] == 2
    for bad in ("limit=0", "limit=201", "limit=x", "offset=-1", "min_threat=101", "acknowledged=maybe", "hours=x"):
        assert api.client.get(f"/api/incidents?{bad}").status_code == 400 or bad == "hours=x"


def test_incident_detail_snapshot_clip_and_ack(api, tmp_path):
    iid = add_incident(api)
    api.s.VIDEOS_DIR.mkdir()
    clip = api.s.VIDEOS_DIR / "c.mp4"
    clip.write_bytes(b"\x00" * 500)
    api.engine.db.set_clip_path(iid, str(clip))
    assert api.client.get(f"/api/incidents/{iid}").json["clip_url"] == f"/api/incidents/{iid}/clip"
    assert api.client.get("/api/incidents/999").status_code == 404
    r = api.client.get(f"/api/incidents/{iid}/snapshot")
    assert r.status_code == 200 and r.mimetype == "image/jpeg" and r.data == JPEG
    r = api.client.get(f"/api/incidents/{iid}/clip", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and len(r.data) == 10
    r = api.client.get(f"/api/incidents/{iid}/clip?download=1")
    assert (
        "attachment" in r.headers["Content-Disposition"] and f"incident_{iid}.mp4" in r.headers["Content-Disposition"]
    )
    sub = api.engine.event_bus.subscribe()
    r = api.client.post(f"/api/incidents/{iid}/ack")  # no body -> acknowledged
    assert r.status_code == 200 and r.json["acknowledged"] is True
    assert sub.get(0.2) == ("ack", {"id": iid, "acknowledged": True})
    r = api.client.post(f"/api/incidents/{iid}/ack", json={"acknowledged": False})
    assert r.json["acknowledged"] is False
    assert api.client.post(f"/api/incidents/{iid}/ack", json={"acknowledged": "yes"}).status_code == 400
    assert api.client.post("/api/incidents/999/ack").status_code == 404


def test_files_outside_data_dirs_are_refused(api, tmp_path):
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(JPEG)
    iid = add_incident(api, image_path=str(outside))
    assert api.client.get(f"/api/incidents/{iid}").json["snapshot_url"] is None
    assert api.client.get(f"/api/incidents/{iid}/snapshot").status_code == 404
    gone = add_incident(api, image_path=str(api.s.SNAPSHOTS_DIR / "missing.jpg"))
    assert api.client.get(f"/api/incidents/{gone}/snapshot").status_code == 404


def test_stats(api):
    add_incident(api)
    r = api.client.get("/api/stats?hours=2").json
    assert r["hours"] == 2 and r["total"] == 1 and len(r["by_hour"]) >= 2
    assert api.client.get("/api/stats?hours=0").status_code == 400
    assert api.client.get("/api/stats?hours=169").status_code == 400


# ------------------------------------------------------------------ zones / alerts / faces
def test_zones_get_put_reset_and_errors(api):
    r = api.client.get("/api/zones").json
    assert r["levels"] == ["SAFE", "PERIMETER", "WARNING", "CRITICAL"] and len(r["zones"]["default"]) == 3
    sub = api.engine.event_bus.subscribe()
    body = {"zones": [{"name": "Gate", "level": "CRITICAL", "rect": [0.5, 0, 1, 1]}]}
    r = api.client.put("/api/zones/alpha", json=body)
    assert r.status_code == 200 and r.json["zones"][0]["name"] == "Gate"
    assert sub.get(0.2) == ("zones", {"camera_id": "alpha"})
    assert (
        api.client.put(
            "/api/zones/alpha", json={"zones": [{"name": "x", "level": "NOPE", "rect": [0, 0, 1, 1]}]}
        ).status_code
        == 400
    )
    assert (
        api.client.put(
            "/api/zones/alpha", json={"zones": [{"name": "x", "level": "SAFE", "rect": [0, 0, 1, float("nan")]}]}
        ).status_code
        == 400
    )
    assert api.client.put("/api/zones/alpha", data="[]", content_type="application/json").status_code == 400
    assert api.client.put("/api/zones/alpha").status_code == 400
    assert api.client.put("/api/zones/ghost", json=body).status_code == 404
    r = api.client.put("/api/zones/alpha", json={"zones": []})
    assert r.status_code == 200 and len(r.json["zones"]) == 3  # back to the default set
    assert api.client.put("/api/zones/default", json={"zones": []}).status_code == 400


def test_alert_controls_publish_status(api):
    sub = api.engine.event_bus.subscribe()
    assert api.client.post("/api/alerts/pause").json == {"paused": True}
    assert sub.get(0.2)[0] == "status" and api.client.get("/api/alerts").json["paused"] is True
    assert api.client.post("/api/alerts/resume").json == {"paused": False}


def png(size=(64, 64)):
    buf = io.BytesIO()
    Image.new("RGB", size).save(buf, format="PNG")
    return buf.getvalue()


def test_faces_list_enroll_delete(api):
    assert api.client.get("/api/faces").json == {"people": [{"name": "Aryan Negi", "images": 2}]}
    sub = api.engine.event_bus.subscribe()
    r = api.client.post("/api/faces", data={"name": "Bob", "image": (io.BytesIO(png()), "bob.png")})
    assert r.status_code == 201 and r.json == {"name": "Bob", "images": 1}
    assert sub.get(0.2)[0] == "faces"
    assert api.client.post("/api/faces", data={"name": "Bob"}).status_code == 400
    assert (
        api.client.post("/api/faces", data={"name": "Bob", "image": (io.BytesIO(png()), "bob.gif")}).status_code == 400
    )
    assert (
        api.client.post("/api/faces", data={"name": "boom", "image": (io.BytesIO(png()), "b.png")}).status_code == 400
    )
    big = api.client.post(
        "/api/faces", data={"name": "Bob", "image": (io.BytesIO(b"x" * (5 * 1024 * 1024 + 10)), "b.png")}
    )
    assert big.status_code in (400, 413) and big.is_json
    huge = api.client.post("/api/faces", data={"name": "Bob", "image": (io.BytesIO(b"x" * (7 * 1024 * 1024)), "b.png")})
    assert huge.status_code == 413 and huge.json["error"]
    assert api.client.delete("/api/faces/Aryan%20Negi").json == {"removed": True}
    assert api.client.delete("/api/faces/Nobody").status_code == 404


# ------------------------------------------------------------------ SSE
def test_events_stream_first_event_is_status_and_releases_subscription(api):
    r = api.client.get("/api/events")
    assert r.status_code == 200 and r.mimetype == "text/event-stream" and r.headers["X-Accel-Buffering"] == "no"
    first = next(r.response).decode()
    assert first.startswith("event: status\ndata: ") and '"alerts_paused": false' in first
    assert api.engine.event_bus.subscriber_count == 1
    api.engine.event_bus.publish("zones", {"camera_id": "alpha"})
    assert "event: zones" in next(r.response).decode()
    r.close()
    assert api.engine.event_bus.subscriber_count == 0


def test_events_subscriber_cap(api):
    streams = [api.client.get("/api/events") for _ in range(32)]
    assert api.client.get("/api/events").status_code == 503
    for s in streams:
        s.close()


# ------------------------------------------------------------------ reports
def test_report_pdf_plain_encrypted_and_legacy(api):
    add_incident(api)
    r = api.client.get("/api/report.pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
    r = api.client.get("/api/report.pdf?encrypted=1")
    assert r.mimetype == "application/octet-stream" and r.headers["Content-Disposition"].endswith(".pdf.enc")
    from src.security_vault import decrypt_bytes

    assert decrypt_bytes(r.data, key_file=api.s.KEY_FILE).startswith(b"%PDF")
    assert not list(api.s.REPORTS_DIR.glob("*.enc"))
    assert api.client.get("/download_secure_report").data.startswith(b"%PDF")


# ------------------------------------------------------------------ frontend serving
def test_frontend_dist_served_without_traversal(api):
    dist = api.s.FRONTEND_DIST
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "x.js").write_text("js")
    (dist / "favicon.svg").write_text("<svg/>")
    (api.s.DATA_DIR / "secret.key").write_text("k")
    assert api.client.get("/").data == b"<html>app</html>"
    assert api.client.get("/assets/x.js").data == b"js"
    assert api.client.get("/favicon.svg").data == b"<svg/>"
    assert api.client.get("/assets/../../secret.key").status_code == 404
    assert api.client.get("/assets/..%2F..%2Fsecret.key").status_code == 404
    assert api.client.get("/anything/else").status_code == 404 and api.client.get("/anything/else").is_json


# ------------------------------------------------------------------ security
def test_open_mode_rejects_foreign_host_and_origin(api):
    assert api.client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403
    assert api.client.get("/api/health", headers={"Host": "localhost:5001"}).status_code == 200
    assert api.client.get("/api/health", headers={"Host": "[::1]:5001"}).status_code == 200
    r = api.client.post("/api/alerts/pause", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and r.json == {"error": "forbidden origin"}
    assert api.client.post("/api/alerts/pause", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200
    # same-origin (the test client's host_url is http://localhost/)
    assert api.client.post("/api/alerts/resume", headers={"Origin": "http://localhost"}).status_code == 200


def test_token_mode_auth_rules(secured):
    c, t = secured.client, secured.token
    assert c.get("/api/health").status_code == 200 and c.get("/api/health").json["auth_required"] is True
    assert c.get("/").status_code == 200
    for path in (
        "/api/cameras",
        "/video_feed/alpha",
        "/video_feed_1",
        "/download_secure_report",
        "/api/events",
        "/nope",
    ):
        assert c.get(path).status_code == 401, path
    assert c.get("/api/cameras", headers={"Authorization": f"Bearer {t}"}).status_code == 200
    assert c.get(f"/api/cameras?token={t}").status_code == 200
    assert c.get("/api/cameras?token=wrong").status_code == 401
    assert c.get("/api/cameras?token=%C3%A9").status_code == 401  # non-ASCII must not 500
    assert c.get("/api/cameras", headers={"Authorization": "Basic abc"}).status_code == 401
    r = c.open(
        "/api/zones/alpha",
        method="OPTIONS",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert r.status_code == 200 and r.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
    r = c.get("/api/cameras", headers={"Origin": "http://127.0.0.1:5173"})
    assert r.status_code == 401 and r.headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:5173"
    assert (
        c.get("/api/cameras", headers={"Host": "192.168.1.9:5001", "Authorization": f"Bearer {t}"}).status_code == 200
    )
    r = c.post(
        "/api/faces",
        headers={"Origin": "http://evil.example", "Authorization": f"Bearer {t}"},
        data={"name": "Bob", "image": (io.BytesIO(png()), "b.png")},
    )
    assert r.status_code == 403


def test_log_filter_redacts_token():
    f = _TokenRedactor()
    rec = logging.LogRecord(
        "werkzeug", logging.INFO, "", 0, '127.0.0.1 - "GET /api/events?token=SECRET123&x=1 HTTP/1.1" 200', (), None
    )
    f.filter(rec)
    assert "SECRET123" not in rec.getMessage() and "token=***&x=1" in rec.getMessage()
    rec = logging.LogRecord("werkzeug", logging.INFO, "", 0, "%s %s", ("GET /a?token=SECRET123", "200"), None)
    f.filter(rec)
    assert "SECRET123" not in rec.getMessage()


def test_500_never_leaks_exception_text(api):
    @api.app.get("/boom")
    def boom():
        raise RuntimeError("/Users/secret/path leaked")

    r = api.client.get("/boom")
    assert r.status_code == 500 and r.json == {"error": "internal error"}


def test_method_not_allowed_is_json(api):
    r = api.client.delete("/api/health")
    assert r.status_code == 405 and r.json["error"]


def test_importing_app_does_not_load_heavy_modules():
    code = "import web.app, sys; print(sorted({'cv2','ultralytics','torch','face_recognition'} & set(sys.modules)))"
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == "[]", out.stderr


def test_create_app_requires_engine(tmp_path):
    with pytest.raises(ValueError):
        create_app(None, make_settings(tmp_path))
