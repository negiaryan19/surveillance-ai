"""Owns every camera worker plus the shared collaborators, and housekeeping.

This module imports only light dependencies at the top so ``web.app`` and the
tests can import it without OpenCV or the models; the heavy modules are
imported inside the default worker factory. Collaborators are injectable for
tests; ``worker_factory`` receives the fully built dependency set and returns
a worker-like object.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("chanakya.engine")

STATUS_INTERVAL = 2.0
RETENTION_INTERVAL = 6 * 3600


class SurveillanceEngine:
    def __init__(
        self,
        settings=None,
        *,
        db=None,
        event_bus=None,
        zone_manager=None,
        face_recognizer=None,
        alert_manager=None,
        worker_factory: Callable | None = None,
    ) -> None:
        if settings is None:
            from config import settings as _settings

            settings = _settings
        self.settings = settings
        self._db = db
        self._event_bus = event_bus
        self._zone_manager = zone_manager
        self._face_recognizer = face_recognizer
        self._alert_manager = alert_manager
        self._worker_factory = worker_factory or self._default_worker_factory

        self._workers: dict[str, object] = {}
        self._cameras: dict[str, object] = {}
        self._order: list[str] = []
        self._started = False
        self._stop = threading.Event()
        self._housekeeper: threading.Thread | None = None
        self._lock = threading.Lock()
        self.started_at: float | None = None

    # ------------------------------------------------------------------ shared collaborators (lazy)
    @property
    def db(self):
        if self._db is None:
            from src.database_manager import DatabaseManager

            self._db = DatabaseManager(self.settings.DB_PATH)
        return self._db

    @property
    def event_bus(self):
        if self._event_bus is None:
            from src.events import EventBus

            self._event_bus = EventBus()
        return self._event_bus

    @property
    def zone_manager(self):
        if self._zone_manager is None:
            from src.zones import ZoneManager

            self._zone_manager = ZoneManager(self.settings.ZONES_FILE)
        return self._zone_manager

    @property
    def face_recognizer(self):
        if self._face_recognizer is None:
            from src.face_recognizer import FaceRecognizer

            self._face_recognizer = FaceRecognizer(self.settings.KNOWN_FACES_DIR, self.settings.ENCODINGS_FILE)
        return self._face_recognizer

    @property
    def alert_manager(self):
        if self._alert_manager is None:
            from src.engine.alert_manager import AlertManager

            self._alert_manager = AlertManager(
                self.db, self.event_bus, snapshots_dir=self.settings.SNAPSHOTS_DIR, serializer=self.serialize_incident
            )
        return self._alert_manager

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        ensure = getattr(self.settings, "ensure_dirs", None)
        if callable(ensure):
            ensure()
        self.started_at = time.time()
        # Touch the shared collaborators so any failure surfaces here, not in a worker thread.
        _ = (self.db, self.event_bus, self.zone_manager, self.face_recognizer, self.alert_manager)

        built = []
        for cam_cfg in self.settings.CAMERAS:
            worker, camera = self._worker_factory(self, cam_cfg)
            built.append((cam_cfg["id"], worker, camera))
        # ByteTrack's id counter is process-global and reset on construction:
        # every tracker must exist and be warm before ANY worker thread runs.
        for cam_id, worker, _ in built:
            for attr in ("tracker", "pose"):
                obj = getattr(worker, attr, None)
                warm = getattr(obj, "warmup", None)
                if callable(warm):
                    try:
                        warm()
                    except Exception:  # noqa: BLE001
                        log.exception("warmup of %s for %s failed", attr, cam_id)
        for cam_id, worker, camera in built:
            self._order.append(cam_id)
            self._workers[cam_id] = worker
            self._cameras[cam_id] = camera
            if camera is not None and hasattr(camera, "start"):
                camera.start()  # calling thread: macOS needs the first open here
        for cam_id in self._order:
            self._workers[cam_id].start()
        self._housekeeper = threading.Thread(target=self._housekeeping, name="housekeeping", daemon=True)
        self._housekeeper.start()
        log.info("engine started with cameras %s", ", ".join(self._order) or "(none)")

    def stop(self) -> None:
        with self._lock:
            if not self._started or self._stop.is_set():
                return
            self._stop.set()
        for worker in self._workers.values():
            try:
                worker.stop()
            except Exception:  # noqa: BLE001
                log.exception("worker stop failed")
        for worker in self._workers.values():
            join = getattr(worker, "join", None)
            if callable(join):
                join(timeout=5.0)
        for worker in self._workers.values():
            recorder = getattr(worker, "recorder", None)
            flush = getattr(recorder, "flush", None)
            if callable(flush):
                try:
                    flush(time.time() + 1e9)
                    wait = getattr(recorder, "wait_idle", None)
                    if callable(wait):
                        wait(30.0)
                except Exception:  # noqa: BLE001
                    log.exception("recorder shutdown failed")
        for camera in self._cameras.values():
            try:
                camera.stop()
            except Exception:  # noqa: BLE001
                log.exception("camera stop failed")
        if self._housekeeper is not None:
            self._housekeeper.join(timeout=2.0)
        log.info("engine stopped")

    # ------------------------------------------------------------------ queries
    def camera_ids(self) -> list[str]:
        return list(self._order)

    def get_worker(self, camera_id: str):
        return self._workers.get(camera_id)

    def cameras(self) -> list[dict]:
        return [self._workers[cid].status() for cid in self._order]

    def status_snapshot(self) -> dict:
        return {"cameras": self.cameras(), "alerts_paused": bool(self.alert_manager.is_paused())}

    def modules(self) -> dict:
        from src.telegram_bot import telegram_configured

        names = sorted(set(self.face_recognizer.known_names))
        return {
            "emotion": {
                "status": "enabled",
                "engine": "facial-landmark-heuristic (experimental)",
                "classes": ["Neutral", "Focused", "Happy", "Surprised", "Tired", "Unknown"],
            },
            "knownFaces": {"count": len(names), "names": names},
            "streams": {
                cid: ("online" if self._workers[cid].status().get("online") else "offline") for cid in self._order
            },
            "telegram": {"configured": bool(telegram_configured())},
            "recorder": {"enabled": True},
        }

    def serialize_incident(self, incident: dict | None) -> dict | None:
        """DB dict -> API dict: file paths become URLs, null unless the file is safely inside the data dirs."""
        if incident is None:
            return None
        safe = self.settings.safe_child
        out = {k: v for k, v in incident.items() if k not in ("image_path", "clip_path")}
        iid = incident["id"]
        out["snapshot_url"] = (
            f"/api/incidents/{iid}/snapshot" if safe(incident.get("image_path"), self.settings.SNAPSHOTS_DIR) else None
        )
        out["clip_url"] = (
            f"/api/incidents/{iid}/clip" if safe(incident.get("clip_path"), self.settings.VIDEOS_DIR) else None
        )
        return out

    # ------------------------------------------------------------------ housekeeping
    def _housekeeping(self) -> None:
        last_retention = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_retention >= RETENTION_INTERVAL:
                last_retention = now
                try:
                    self.run_retention()
                except Exception:  # noqa: BLE001
                    log.exception("retention failed")
            if self.event_bus.subscriber_count > 0:
                try:
                    self.event_bus.publish("status", self.status_snapshot())
                except Exception:  # noqa: BLE001
                    log.exception("status publish failed")
            self._stop.wait(STATUS_INTERVAL)

    def run_retention(self) -> int:
        """Delete incidents and media older than RETENTION_DAYS; returns files removed."""
        days = int(getattr(self.settings, "RETENTION_DAYS", 0) or 0)
        if days <= 0:
            return 0
        removed = 0
        safe = self.settings.safe_child
        for row in self.db.purge_older_than(days):
            for key, root in (("image_path", self.settings.SNAPSHOTS_DIR), ("clip_path", self.settings.VIDEOS_DIR)):
                path = safe(row.get(key), root)
                if path is not None:
                    try:
                        path.unlink()
                        removed += 1
                    except OSError:
                        pass
        # Orphan sweep: files whose DB row never existed or whose delete crashed midway.
        cutoff = time.time() - days * 86400
        for media_dir, patterns in ((self.settings.SNAPSHOTS_DIR, ("*.jpg",)), (self.settings.VIDEOS_DIR, ("*.mp4",))):
            root = Path(media_dir)
            if not root.is_dir():
                continue
            for pattern in patterns:
                for path in root.glob(pattern):
                    try:
                        if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff:
                            path.unlink()
                            removed += 1
                    except OSError:
                        pass
        if removed:
            log.info("retention removed %d files older than %d days", removed, days)
        return removed

    # ------------------------------------------------------------------ default wiring
    def _default_worker_factory(self, engine, cam_cfg: dict):
        from src.anomaly_detector import AnomalyDetector
        from src.emotion_detector import EmotionDetector
        from src.engine.camera import ThreadedCamera
        from src.engine.detectors import PoseEstimator, YoloTracker
        from src.engine.worker import CameraWorker
        from src.night_vision import NightVision
        from src.predictor import MovementPredictor
        from src.threat_assessor import ThreatAssessor
        from src.video_recorder import VideoRecorder

        s = self.settings
        camera = ThreadedCamera(cam_cfg["source"])
        worker = CameraWorker(
            cam_cfg,
            camera=camera,
            tracker=YoloTracker(s.MODEL_PATH, s.THREAT_CLASSES, s.CONFIDENCE_LIMIT, s.CLASS_CONFIDENCE),
            pose=PoseEstimator(s.POSE_MODEL_PATH),
            zone_manager=self.zone_manager,
            alert_manager=self.alert_manager,
            face_recognizer=self.face_recognizer,
            emotion_detector=EmotionDetector(),
            threat_assessor=ThreatAssessor(),
            anomaly_detector=AnomalyDetector(),
            night_vision=NightVision(),
            recorder=VideoRecorder(s.VIDEOS_DIR),
            predictor=MovementPredictor(),
            db=self.db,
            settings=s,
            on_incident_updated=self._publish_incident_updated,
        )
        return worker, camera

    def _publish_incident_updated(self, incident_id: int) -> None:
        self.event_bus.publish("incident_updated", self.serialize_incident(self.db.get_incident(incident_id)))


# ---------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Headless smoke run of the surveillance engine.")
    parser.add_argument("--source", required=True, help="video file path or camera index")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--allow-camera", action="store_true", help="permit an integer (webcam) source")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from config import settings

    source: int | str = args.source
    if str(source).isdigit():
        if not args.allow_camera:
            print("refusing to open a webcam without --allow-camera", file=sys.stderr)
            return 2
        source = int(source)
    settings.CAMERAS = [{"id": "demo", "name": "DEMO", "source": source}]
    engine = SurveillanceEngine(settings)
    engine.start()
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            time.sleep(1.0)
            for status in engine.cameras():
                print(f"{status['name']}: online={status['online']} fps={status['fps']} tracks={status['tracks']}")
    finally:
        engine.stop()
    items, total = engine.db.list_incidents(limit=5)
    print(f"incidents in db: {total}")
    for inc in items:
        print(
            f"  #{inc['id']} {inc['timestamp']} {inc['object_type']} {inc['threat_score']}% {inc['zone_level']} snapshot={bool(inc['image_path'])}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
