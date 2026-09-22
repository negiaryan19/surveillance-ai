import threading

import numpy as np
import pytest

from src.database_manager import DatabaseManager
from src.engine.alert_manager import AlertManager
from src.engine.track_state import TrackRegistry
from src.events import EventBus
from src.liveness_detector import BlinkTracker


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    db = DatabaseManager(tmp_path / "t.db")
    bus = EventBus()
    sub = bus.subscribe()
    sent = []
    written = []
    clock = Clock()

    def writer(path, frame):
        written.append(path)
        return True

    am = AlertManager(
        db,
        bus,
        notifier=lambda *a: sent.append(a),
        snapshot_writer=writer,
        snapshots_dir=tmp_path / "snaps",
        serializer=lambda d: {**d, "serialized": True},
        min_score=70,
        min_track_age=2.0,
        track_cooldown=60.0,
        escalation_delta=15,
        camera_min_interval=3.0,
        notify_min_interval=30.0,
        weapon_min_hits=4,
        weapon_alert_interval=10.0,
        clock=clock,
    )
    return {"db": db, "bus": bus, "sub": sub, "sent": sent, "written": written, "am": am, "clock": clock}


def threat(track_id=1, score=85, first_seen=0.0, weapon=False, **kw):
    reg = TrackRegistry(blink_factory=lambda: BlinkTracker())
    t = reg.get_or_create(track_id, 43 if weapon else 0, "Weapon (Knife)" if weapon else "Person", first_seen)
    t.first_seen = first_seen
    t.score, t.category = score, "CRITICAL" if score >= 70 else "WARNING"
    t.zone_level, t.reasons, t.bbox = "WARNING", ["Unknown Identity"], (10, 10, 50, 90)
    t.has_weapon = weapon
    for k, v in kw.items():
        setattr(t, k, v)
    return t


def consider(env, t, now=None, cam="alpha"):
    return env["am"].consider(
        camera_id=cam, camera_name=cam.upper(), track=t, frame=np.zeros((4, 4, 3), np.uint8), now=now
    )


def test_alert_logs_publishes_snapshots_and_notifies(env):
    iid = consider(env, threat(), now=100.0)
    assert iid == 1
    inc = env["db"].get_incident(1)
    assert inc["camera"] == "alpha" and inc["identity"] is None and inc["emotion"] is None
    assert inc["reasons"] == ["Unknown Identity"] and inc["image_path"].endswith(".jpg")
    assert env["written"][0].startswith(str(env["am"].snapshots_dir))
    kind, data = env["sub"].get(0.5)
    assert kind == "incident" and data["serialized"] and data["id"] == 1
    assert len(env["sent"]) == 1 and env["sent"][0][1] == 85 and "ALPHA" in env["sent"][0][0]


def test_below_threshold_or_authorized_never_alerts(env):
    assert consider(env, threat(score=69), now=100.0) is None
    assert consider(env, threat(score=99, is_authorized=True), now=100.0) is None


def test_young_track_waits_unless_weapon(env):
    assert consider(env, threat(first_seen=99.0), now=100.0) is None
    w = threat(track_id=9, score=100, first_seen=99.5, weapon=True)
    w.hits = 4
    assert consider(env, w, now=100.0) is not None


def test_weapon_needs_min_hits(env):
    w = threat(track_id=9, score=100, weapon=True)
    w.hits = 3
    assert consider(env, w, now=100.0) is None
    w.hits = 4
    assert consider(env, w, now=100.0) is not None


def test_verifying_person_is_not_alerted(env):
    assert consider(env, threat(face_status="VERIFYING"), now=100.0) is None


def test_dedup_cooldown_and_escalation(env):
    t = threat()
    assert consider(env, t, now=100.0) == 1
    assert consider(env, t, now=101.0) is None
    t.score = 99  # +14 < escalation delta
    assert consider(env, t, now=102.0) is None
    t.score = 100  # +15
    assert consider(env, t, now=103.0) == 2
    assert consider(env, t, now=104.0) is None
    assert consider(env, t, now=103.0 + 60.0) == 3  # cooldown elapsed


def test_per_camera_spacing_and_weapon_exemption(env):
    assert consider(env, threat(track_id=1), now=100.0) == 1
    assert consider(env, threat(track_id=2), now=101.0) is None  # < 3 s on the same camera
    assert consider(env, threat(track_id=2), now=101.0, cam="bravo") == 2  # other camera fine
    w = threat(track_id=3, score=100, weapon=True)
    w.hits = 10
    assert consider(env, w, now=101.5) == 3  # weapons ignore the 3 s spacing
    w2 = threat(track_id=4, score=100, weapon=True)
    w2.hits = 10
    assert consider(env, w2, now=105.0) is None  # but one weapon alert per 10 s
    assert consider(env, w2, now=112.0) == 4


def test_notifier_rate_limited_but_incidents_still_logged(env):
    assert consider(env, threat(track_id=1), now=100.0) == 1
    assert consider(env, threat(track_id=2), now=104.0) == 2
    assert len(env["sent"]) == 1  # second notification suppressed for 30 s
    assert consider(env, threat(track_id=3, score=100), now=108.0) == 3
    assert len(env["sent"]) == 2  # escalation (+15) breaks through
    assert consider(env, threat(track_id=4), now=140.0) == 4
    assert len(env["sent"]) == 3
    assert env["db"].list_incidents()[1] == 4


def test_pause_silences_notifier_only(env):
    env["am"].pause()
    assert env["am"].is_paused()
    assert consider(env, threat(), now=100.0) == 1
    assert env["sent"] == []
    env["am"].resume()
    assert consider(env, threat(track_id=2), now=110.0) == 2
    assert len(env["sent"]) == 1


def test_snapshot_failure_and_notifier_exception_are_contained(env, tmp_path):
    def bad_writer(path, frame):
        return False

    def boom(*a):
        raise RuntimeError("telegram down")

    am = AlertManager(
        env["db"],
        env["bus"],
        notifier=boom,
        snapshot_writer=bad_writer,
        snapshots_dir=tmp_path / "s",
        min_track_age=0,
        clock=env["clock"],
    )
    iid = am.consider(
        camera_id="alpha", camera_name="A", track=threat(), frame=np.zeros((2, 2, 3), np.uint8), now=100.0
    )
    assert iid == 1 and env["db"].get_incident(1)["image_path"] is None


def test_forget_resets_dedup(env):
    t = threat()
    assert consider(env, t, now=100.0) == 1
    env["am"].forget("alpha", [1])
    assert consider(env, t, now=104.0) == 2


def test_concurrent_consider_respects_camera_spacing(env):
    ids = []
    tracks = [threat(track_id=i) for i in range(1, 9)]

    def run(t):
        ids.append(consider(env, t, now=100.0))

    threads = [threading.Thread(target=run, args=(t,)) for t in tracks]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len([i for i in ids if i is not None]) == 1
