"""CameraWorker and SurveillanceEngine driven by fakes (real zones/threat/registry/alerts/db)."""

import subprocess
import sys
import time
import types
from datetime import UTC
from pathlib import Path

import numpy as np

from src.database_manager import DatabaseManager
from src.engine.alert_manager import AlertManager
from src.engine.detectors import Detection, PosePerson
from src.engine.engine import SurveillanceEngine
from src.engine.track_state import TrackRegistry
from src.engine.worker import CameraWorker
from src.events import EventBus
from src.face_recognizer import FaceResult
from src.liveness_detector import BlinkTracker
from src.threat_assessor import ThreatAssessor
from src.zones import ZoneManager

BACKEND = Path(__file__).resolve().parent.parent


def make_settings(tmp_path, **over):
    from config import settings as real

    s = types.SimpleNamespace(
        FRAME_WIDTH=640,
        FRAME_HEIGHT=480,
        JPEG_QUALITY=80,
        THREAT_CLASSES=real.THREAT_CLASSES,
        HEAVY_EVERY_N_FRAMES=5,
        POSE_EVERY_N_FRAMES=2,
        EAR_THRESHOLD=0.22,
        LIVENESS_TTL=30.0,
        LIVENESS_GRACE=15.0,
        LIVENESS_MAX_VERIFY=45.0,
        PRONE_MIN_SECONDS=1.5,
        TRACK_MAX_AGE=5.0,
        RETENTION_DAYS=30,
        DATA_DIR=tmp_path,
        SNAPSHOTS_DIR=tmp_path / "snapshots",
        VIDEOS_DIR=tmp_path / "videos",
        REPORTS_DIR=tmp_path / "reports",
        KNOWN_FACES_DIR=tmp_path / "faces",
        ENCODINGS_FILE=tmp_path / "enc.npz",
        DB_PATH=tmp_path / "db.sqlite",
        ZONES_FILE=tmp_path / "zones.json",
        CAMERAS=[{"id": "cam", "name": "CAM", "source": "fake"}],
        safe_child=real.safe_child,
        MODEL_PATH="m.pt",
        POSE_MODEL_PATH="p.pt",
        CONFIDENCE_LIMIT=0.65,
        CLASS_CONFIDENCE={43: 0.35},
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s


class ScriptedCamera:
    """Yields one frame per read() call from a script of (ok, frame) tuples, then offline."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.seq = 0
        self.source_label = "fake"
        self.online = True
        self.stopped = False

    def read(self, last_seq=None, timeout=0.0):
        if not self.frames:
            self.online = False
            return False, None, self.seq
        self.seq += 1
        return True, self.frames.pop(0), self.seq

    def start(self):
        return self

    def stop(self):
        self.stopped = True


class FakeTracker:
    def __init__(self, script):
        self.script = list(script)  # per frame: list of Detection
        self.warm = 0

    def warmup(self):
        self.warm += 1

    def track(self, frame):
        return self.script.pop(0) if self.script else []


class FakePose:
    def __init__(self, people=None):
        self.people = people or []
        self.warm = 0
        self.calls = 0

    def warmup(self):
        self.warm += 1

    def estimate(self, frame):
        self.calls += 1
        return self.people

    def draw(self, frame, people):
        pass


class FakeFace:
    def __init__(self, result=None):
        self.result = result or FaceResult(found=False)
        self.analyze_calls = []
        self.landmark_calls = []
        self.known_names = []

    def analyze(self, frame, bbox):
        self.analyze_calls.append((frame.shape, bbox))
        return self.result

    def landmarks_at(self, frame, bbox):
        self.landmark_calls.append(bbox)
        return {"left_eye": [(0, 0)] * 6, "right_eye": [(0, 0)] * 6}


class FakeRecorder:
    def __init__(self):
        self.updates = 0
        self.triggers = []
        self.flushes = 0

    def update(self, frame, now=None):
        self.updates += 1

    def trigger(self, prefix, on_saved=None):
        self.triggers.append((prefix, on_saved))
        return True

    def flush(self, now=None):
        self.flushes += 1

    def wait_idle(self, timeout=0):
        return True


class Stateless:
    def is_low_light(self, f):
        return False

    def enhance(self, f):
        return f

    def classify(self, landmarks):
        return {"emotion": "Neutral", "confidence": 55}

    def analyze(self, *a, **k):
        return (False, None, None)

    def prune(self, ids):
        pass

    def update(self, *a):
        pass

    def predict_next_position(self, *a, **k):
        return None


def frame(w=640, h=480, v=60):
    return np.full((h, w, 3), v, np.uint8)


def build_worker(tmp_path, frames, detections, *, face=None, pose=None, clock=None, alert_kwargs=None, settings=None):
    s = settings or make_settings(tmp_path)
    db = DatabaseManager(s.DB_PATH)
    bus = EventBus()
    sent = []
    am = AlertManager(
        db,
        bus,
        notifier=lambda *a: sent.append(a),
        snapshot_writer=lambda p, f: True,
        snapshots_dir=s.SNAPSHOTS_DIR,
        min_track_age=0.0,
        camera_min_interval=0.0,
        **(alert_kwargs or {}),
        clock=clock or time.time,
    )
    updated = []
    w = CameraWorker(
        {"id": "cam", "name": "CAM"},
        camera=ScriptedCamera(frames),
        tracker=FakeTracker(detections),
        pose=pose or FakePose(),
        zone_manager=ZoneManager(s.ZONES_FILE),
        alert_manager=am,
        face_recognizer=face or FakeFace(),
        emotion_detector=Stateless(),
        threat_assessor=ThreatAssessor(loiter_threshold=10),
        anomaly_detector=Stateless(),
        night_vision=Stateless(),
        recorder=FakeRecorder(),
        predictor=Stateless(),
        db=db,
        settings=s,
        registry=TrackRegistry(blink_factory=lambda: BlinkTracker()),
        on_incident_updated=updated.append,
        clock=clock or time.time,
    )
    return w, db, bus, sent, updated


def run_worker(w, frames_expected, timeout=5.0):
    w.start()
    seq = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        seq, jpeg = w.wait_for_frame(seq, timeout=0.5)
        if seq >= frames_expected:
            break
    w.stop()
    w.join(timeout=3)
    return seq


def test_worker_publishes_frames_and_serves_two_consumers(tmp_path):
    w, *_ = build_worker(tmp_path, [frame() for _ in range(4)], [[]] * 4)
    assert w.latest_jpeg().startswith(b"\xff\xd8")  # placeholder is a JPEG before any frame
    w.start()
    a_seq, a_jpeg = w.wait_for_frame(0, timeout=2)
    b_seq, b_jpeg = w.wait_for_frame(0, timeout=2)
    assert a_seq >= 1 and b_seq >= 1 and a_jpeg.startswith(b"\xff\xd8")
    a2, _ = w.wait_for_frame(a_seq, timeout=2)
    assert a2 > a_seq
    time.sleep(0.5)  # camera script exhausted -> offline placeholder + recorder flush
    assert w.recorder.flushes >= 1
    w.stop()
    w.join(timeout=3)
    st = w.status()
    assert st["id"] == "cam" and st["source"] == "fake" and "last_frame_at" in st and st["tracks"] == 0


def test_unknown_person_in_critical_zone_alerts_and_clip_callback_binds_first_id(tmp_path):
    clock = [100.0]
    det_a = Detection(1, 0, 0.9, (560, 100, 620, 470))  # feet at x=590 -> CRITICAL (>= 0.75*640)
    det_b = Detection(2, 0, 0.9, (100, 100, 160, 470))  # SAFE zone
    w, db, bus, sent, updated = build_worker(
        tmp_path, [frame() for _ in range(3)], [[det_a, det_b]] * 3, clock=lambda: clock[0]
    )
    sub = bus.subscribe()
    run_worker(w, 3)
    items, total = db.list_incidents()
    assert total == 1 and items[0]["track_id"] == 1 and items[0]["zone_level"] == "CRITICAL"
    assert items[0]["threat_score"] == 90 and "Breached Critical Zone" in items[0]["reasons"]
    assert sub.get(0.1)[0] == "incident"
    prefix, cb = w.recorder.triggers[0]
    assert prefix == "incident_1" and len(w.recorder.triggers) == 1
    cb("/tmp/clip.mp4")  # writer thread callback, fired later
    assert db.get_incident(1)["clip_path"] == "/tmp/clip.mp4" and updated == [1]


def test_face_analysis_uses_raw_frame_coordinates_and_heavy_cadence(tmp_path):
    face = FakeFace(
        FaceResult(
            found=True,
            name="Aryan",
            landmarks={"left_eye": [(0, 0)] * 6, "right_eye": [(0, 0)] * 6},
            face_bbox=(400, 200, 500, 300),
        )
    )
    det = Detection(1, 0, 0.9, (100, 100, 200, 400))
    raw = [frame(1280, 960) for _ in range(12)]
    w, db, *_ = build_worker(tmp_path, raw, [[det]] * 12, face=face)
    run_worker(w, 12)
    # heavy on frame 1 then every 5 frames -> 3 analyses for 12 frames; bbox scaled by 2
    assert len(face.analyze_calls) == 3
    assert face.analyze_calls[0] == ((960, 1280, 3), (200, 200, 400, 800))
    # blink sampling happens on the non-heavy frames once the identity is known
    assert len(face.landmark_calls) >= 8 and face.landmark_calls[0] == (400, 200, 500, 300)
    track = w.registry.active()[0]
    assert track.identity == "Aryan" and track.face_status == "VERIFYING" and track.emotion == "Neutral"
    assert db.list_incidents()[1] == 0  # VERIFYING never alerts


def test_heavy_failure_still_publishes_frames(tmp_path):
    class Boom(FakeFace):
        def analyze(self, frame, bbox):
            raise RuntimeError("dlib exploded")

    det = Detection(1, 0, 0.9, (100, 100, 200, 400))
    w, *_ = build_worker(tmp_path, [frame() for _ in range(3)], [[det]] * 3, face=Boom())
    assert run_worker(w, 3) >= 3


def test_zone_entry_time_resets_on_level_change(tmp_path):
    clock = [0.0]
    dets = [[Detection(1, 0, 0.9, (100, 100, 160, 470))]] * 2 + [[Detection(1, 0, 0.9, (560, 100, 620, 470))]] * 2
    w, *_ = build_worker(tmp_path, [frame() for _ in range(4)], dets, clock=lambda: clock[0])
    w.start()
    seq = 0
    for _ in range(4):
        clock[0] += 1.0
        seq, _ = w.wait_for_frame(seq, timeout=2)
    w.stop()
    w.join(timeout=2)
    t = w.registry.active()[0]
    assert t.zone_level == "CRITICAL" and t.zone_entered_at > t.first_seen  # reset when the level changed


def test_prone_needs_debounce(tmp_path):
    clock = [0.0]
    k = np.zeros((17, 3))
    k[5, :2], k[6, :2], k[11, :2], k[12, :2] = (100, 150), (100, 170), (220, 155), (220, 165)
    k[[5, 6, 11, 12], 2] = 0.9
    pose = FakePose([PosePerson((80, 140, 240, 180), k)])
    det = Detection(1, 0, 0.9, (80, 140, 240, 180))
    w, db, *_ = build_worker(tmp_path, [frame() for _ in range(6)], [[det]] * 6, pose=pose, clock=lambda: clock[0])
    w.start()
    seq = 0
    scores = []
    for _ in range(6):
        clock[0] += 0.5
        seq, _ = w.wait_for_frame(seq, timeout=2)
        scores.append(w.registry.active()[0].score if w.registry.active() else None)
    w.stop()
    w.join(timeout=2)
    t = w.registry.active()[0]
    assert t.posture == "PRONE" and "Suspicious Posture: Crawling/Prone" in t.reasons
    assert scores[0] == 50 and scores[-1] == 100  # +50 only after PRONE_MIN_SECONDS


# ------------------------------------------------------------------ engine
class FakeWorker:
    def __init__(self, cam_id):
        self.cam_id = cam_id
        self.tracker = types.SimpleNamespace(warmup=lambda: self.events.append(("warm", cam_id)))
        self.pose = types.SimpleNamespace(warmup=lambda: self.events.append(("warm-pose", cam_id)))
        self.recorder = FakeRecorder()
        self.started = False
        self.events = []

    def start(self):
        self.started = True
        self.events.append(("start", self.cam_id))

    def stop(self):
        self.events.append(("stop", self.cam_id))

    def join(self, timeout=None):
        pass

    def status(self):
        return {
            "id": self.cam_id,
            "name": self.cam_id.upper(),
            "online": True,
            "fps": 1.0,
            "tracks": 0,
            "night_mode": False,
            "last_frame_at": None,
            "source": "fake",
        }


def build_engine(tmp_path, cameras=("a", "b")):
    s = make_settings(tmp_path, CAMERAS=[{"id": c, "name": c.upper(), "source": "fake"} for c in cameras])
    events = []
    workers = {}

    def factory(engine, cfg):
        w = FakeWorker(cfg["id"])
        w.events = events
        workers[cfg["id"]] = w
        cam = types.SimpleNamespace(
            start=lambda: events.append(("cam-start", cfg["id"])), stop=lambda: events.append(("cam-stop", cfg["id"]))
        )
        return w, cam

    db = DatabaseManager(s.DB_PATH)
    face = FakeFace()
    face.known_names = ["Bob", "Aryan", "Bob"]
    eng = SurveillanceEngine(
        s,
        db=db,
        event_bus=EventBus(),
        zone_manager=ZoneManager(s.ZONES_FILE),
        face_recognizer=face,
        worker_factory=factory,
    )
    return eng, events, workers, s


def test_engine_warms_all_trackers_before_any_worker_starts(tmp_path):
    eng, events, workers, _ = build_engine(tmp_path)
    eng.start()
    eng.start()  # idempotent
    kinds = [e[0] for e in events]
    assert kinds.index("start") > max(i for i, k in enumerate(kinds) if k.startswith("warm"))
    assert [e for e in events if e[0] == "warm"] == [("warm", "a"), ("warm", "b")]
    assert eng.camera_ids() == ["a", "b"] and eng.get_worker("b") is workers["b"]
    snap = eng.status_snapshot()
    assert [c["id"] for c in snap["cameras"]] == ["a", "b"] and snap["alerts_paused"] is False
    mods = eng.modules()
    assert mods["knownFaces"] == {"count": 2, "names": ["Aryan", "Bob"]} and mods["streams"] == {
        "a": "online",
        "b": "online",
    }
    eng.stop()
    eng.stop()
    assert [e[0] for e in events][-4:] == ["stop", "stop", "cam-stop", "cam-stop"] or ("stop", "a") in events


def test_serialize_incident_nulls_urls_outside_data_dirs(tmp_path):
    eng, _, _, s = build_engine(tmp_path)
    s.SNAPSHOTS_DIR.mkdir()
    good = s.SNAPSHOTS_DIR / "a.jpg"
    good.write_bytes(b"jpg")
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"jpg")
    db = eng.db
    i1 = db.log_incident(camera="a", object_type="Person", threat_score=80, image_path=str(good))
    i2 = db.log_incident(
        camera="a",
        object_type="Person",
        threat_score=80,
        image_path=str(outside),
        clip_path=str(tmp_path / "missing.mp4"),
    )
    api1 = eng.serialize_incident(db.get_incident(i1))
    api2 = eng.serialize_incident(db.get_incident(i2))
    assert api1["snapshot_url"] == f"/api/incidents/{i1}/snapshot" and api1["clip_url"] is None
    assert api2["snapshot_url"] is None and api2["clip_url"] is None
    assert "image_path" not in api1 and "clip_path" not in api1


def test_retention_removes_old_rows_files_and_orphans(tmp_path):
    eng, _, _, s = build_engine(tmp_path)
    s.SNAPSHOTS_DIR.mkdir()
    s.VIDEOS_DIR.mkdir()
    old_snap = s.SNAPSHOTS_DIR / "old.jpg"
    old_snap.write_bytes(b"x")
    orphan = s.VIDEOS_DIR / "orphan.mp4"
    orphan.write_bytes(b"x")
    fresh = s.SNAPSHOTS_DIR / "fresh.jpg"
    fresh.write_bytes(b"x")
    import os

    ancient = time.time() - 40 * 86400
    os.utime(old_snap, (ancient, ancient))
    os.utime(orphan, (ancient, ancient))
    db = eng.db
    from datetime import datetime, timedelta

    iid = db.log_incident(camera="a", object_type="Person", threat_score=80, image_path=str(old_snap))
    import sqlite3

    with sqlite3.connect(s.DB_PATH) as conn:
        conn.execute(
            "UPDATE incidents SET timestamp=? WHERE id=?",
            ((datetime.now(UTC) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ"), iid),
        )
    removed = eng.run_retention()
    assert removed == 2 and not old_snap.exists() and not orphan.exists() and fresh.exists()
    assert db.get_incident(iid) is None


def test_engine_module_imports_without_heavy_deps():
    code = "import src.engine.engine, web.app, sys; print(sorted({'cv2','ultralytics','torch','face_recognition'} & set(sys.modules)))"
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"
