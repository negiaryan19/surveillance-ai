"""Replay a video clip through the real detection pipeline, deterministically.

The worker's per-frame pipeline (`CameraWorker.process_frame`) is driven
synchronously from this process with an injected clock that advances by
exactly 1/fps per frame, so the same clip always produces the same track
timeline regardless of machine speed. Every frame's tracks and every incident
are written as JSON lines for `tools/evaluate.py`.

Usage:
    python -m tools.replay --clip demo.mp4 --out run.jsonl [--fps 15] [--max-frames N] [--data-dir DIR]

Nothing is sent to Telegram and no webcam is opened. Runs need the heavy
dependencies (ultralytics, face_recognition) and the model files.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import time
import types
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

log = logging.getLogger("chanakya.replay")


class _StillCamera:
    """Camera stand-in: the worker never reads from it, but status() does."""

    online = True

    def __init__(self, label: str) -> None:
        self.source_label = label


class _NoRecorder:
    """Recording is irrelevant to accuracy metrics and would slow the replay."""

    recording_active = False

    def update(self, frame, now=None) -> None:
        return None

    def trigger(self, prefix, on_saved=None, now=None) -> bool:
        return False

    def flush(self, now=None) -> None:
        return None

    def wait_idle(self, timeout=0.0) -> bool:
        return True


def _replay_settings(data_dir: Path):
    """A private copy of the settings module pointing every path at ``data_dir``."""
    from config import settings as real

    s = types.SimpleNamespace(**{k: getattr(real, k) for k in dir(real) if k.isupper()})
    s.DATA_DIR = data_dir
    s.SNAPSHOTS_DIR = data_dir / "snapshots"
    s.VIDEOS_DIR = data_dir / "videos"
    s.REPORTS_DIR = data_dir / "reports"
    s.KNOWN_FACES_DIR = data_dir / "known_faces"
    s.ENCODINGS_FILE = data_dir / "face_encodings.npz"
    s.DB_PATH = data_dir / "chanakya.db"
    s.ZONES_FILE = data_dir / "zones.json"
    s.safe_child = real.safe_child
    for d in (s.SNAPSHOTS_DIR, s.VIDEOS_DIR, s.REPORTS_DIR, s.KNOWN_FACES_DIR):
        d.mkdir(parents=True, exist_ok=True)
    return s


def build_worker(
    settings, clock, *, known_faces: Path | None = None, zones_file: Path | None = None, conf: float | None = None
):
    """Wire a CameraWorker exactly as the engine does, minus threads and Telegram."""
    from src.anomaly_detector import AnomalyDetector
    from src.database_manager import DatabaseManager
    from src.emotion_detector import EmotionDetector
    from src.engine.alert_manager import AlertManager
    from src.engine.detectors import PoseEstimator, YoloTracker
    from src.engine.worker import CameraWorker
    from src.events import EventBus
    from src.face_recognizer import FaceRecognizer
    from src.night_vision import NightVision
    from src.predictor import MovementPredictor
    from src.threat_assessor import ThreatAssessor
    from src.zones import ZoneManager

    db = DatabaseManager(settings.DB_PATH)
    bus = EventBus()
    notified: list[tuple] = []
    alert_manager = AlertManager(
        db,
        bus,
        notifier=lambda *args: notified.append(args),
        snapshots_dir=settings.SNAPSHOTS_DIR,
        clock=clock,
    )
    floor = settings.CONFIDENCE_LIMIT if conf is None else float(conf)
    tracker = YoloTracker(settings.MODEL_PATH, settings.THREAT_CLASSES, floor, settings.CLASS_CONFIDENCE)
    pose = PoseEstimator(settings.POSE_MODEL_PATH)
    tracker.warmup()
    pose.warmup()
    worker = CameraWorker(
        {"id": "replay", "name": "REPLAY"},
        camera=_StillCamera("replay"),
        tracker=tracker,
        pose=pose,
        zone_manager=ZoneManager(zones_file or settings.ZONES_FILE),
        alert_manager=alert_manager,
        face_recognizer=FaceRecognizer(known_faces or settings.KNOWN_FACES_DIR, settings.ENCODINGS_FILE),
        emotion_detector=EmotionDetector(),
        threat_assessor=ThreatAssessor(),
        anomaly_detector=AnomalyDetector(),
        night_vision=NightVision(),
        recorder=_NoRecorder(),
        predictor=MovementPredictor(),
        db=db,
        settings=settings,
        clock=clock,
    )
    return worker, db, notified


def _track_record(track) -> dict:
    return {
        "track_id": track.track_id,
        "class_id": track.class_id,
        "obj_type": track.obj_type,
        "bbox": [int(v) for v in track.bbox],
        "zone": track.zone_level,
        "identity": track.identity,
        "face_status": track.face_status,
        "posture": track.posture,
        "anomaly": track.anomaly_type,
        "score": track.score,
        "category": track.category,
    }


def replay(
    clip: Path,
    out: Path,
    *,
    fps: float,
    max_frames: int | None,
    data_dir: Path,
    known_faces: Path | None = None,
    zones_file: Path | None = None,
    conf: float | None = None,
) -> dict:
    import cv2

    settings = _replay_settings(data_dir)
    state = {"t": 0.0}
    worker, db, notified = build_worker(
        settings, lambda: state["t"], known_faces=known_faces, zones_file=zones_file, conf=conf
    )

    cap = cv2.VideoCapture(str(clip))
    if not cap.isOpened():
        raise SystemExit(f"cannot open {clip}")
    step = 1.0 / fps
    seen_incidents = 0
    frames = 0
    wall_start = time.perf_counter()
    with open(out, "w", encoding="utf-8") as fh:
        while True:
            ok, raw = cap.read()
            if not ok or raw is None or (max_frames is not None and frames >= max_frames):
                break
            state["t"] = frames * step
            worker.process_frame(raw)
            now = state["t"]
            active = [t for t in worker.registry.active() if now - t.last_seen < step / 2]
            record = {"frame": frames, "t": round(now, 4), "tracks": [_track_record(t) for t in active]}
            items, total = db.list_incidents(limit=50)
            if total > seen_incidents:
                fresh = sorted((i for i in items if i["id"] > seen_incidents), key=lambda i: i["id"])
                record["incidents"] = [
                    {
                        "id": i["id"],
                        "track_id": i["track_id"],
                        "zone": i["zone_level"],
                        "score": i["threat_score"],
                        "reasons": i["reasons"],
                        "identity": i["identity"],
                    }
                    for i in fresh
                ]
                seen_incidents = total
            fh.write(json.dumps(record) + "\n")
            frames += 1
    cap.release()
    wall = time.perf_counter() - wall_start
    summary = {
        "clip": str(clip),
        "frames": frames,
        "fps_nominal": fps,
        "conf": conf,
        "fps_processed": round(frames / wall, 2) if wall > 0 else None,
        "incidents": seen_incidents,
        "notifications": len(notified),
        "tracks_seen": len({t.track_id for t in worker.registry.active()}),
    }
    with open(out.with_suffix(".summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clip", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="JSONL of per-frame tracks and incidents")
    parser.add_argument("--fps", type=float, default=15.0, help="clock advance per frame (default 15)")
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--data-dir", type=Path, default=None, help="scratch data dir (default: a temp dir)")
    parser.add_argument("--known-faces", type=Path, default=None, help="folder of enrolled faces to use")
    parser.add_argument("--zones", type=Path, default=None, help="zones.json to evaluate with")
    parser.add_argument(
        "--conf", type=float, default=None, help="override the detector confidence floor (threshold tuning)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    data_dir = args.data_dir or Path(tempfile.mkdtemp(prefix="chanakya-replay-"))
    summary = replay(
        args.clip,
        args.out,
        fps=args.fps,
        max_frames=args.max_frames,
        data_dir=data_dir,
        known_faces=args.known_faces,
        zones_file=args.zones,
        conf=args.conf,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
