"""One always-on processing thread per camera.

Detection no longer lives inside an HTTP response generator: the worker runs
whether or not anyone is watching, and MJPEG viewers merely wait for the
latest encoded frame. Cheap work (tracking, zones, posture, blink sampling)
happens every frame; expensive work (face recognition, emotion) every
``HEAVY_EVERY_N_FRAMES`` frames per track, in its own try/except so a dlib
hiccup never stops a frame from being published.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

import cv2
import numpy as np

from src.engine.posture import match_pose_to_bbox, posture_from_keypoints

log = logging.getLogger("chanakya.worker")

WEAPON_CLASS = 43
POSTURE_UNKNOWN_TOLERANCE = 0.5
PRUNE_INTERVAL = 1.0
FACE_BBOX_MAX_AGE = 1.0


class _RateLimitedLog:
    """Log the same failure at most once per ``interval`` seconds."""

    def __init__(self, interval: float = 10.0) -> None:
        self.interval = interval
        self._last: dict[str, float] = {}

    def exception(self, key: str, message: str, *args) -> None:
        now = time.monotonic()
        if now - self._last.get(key, -1e9) >= self.interval:
            self._last[key] = now
            log.exception(message, *args)


class CameraWorker(threading.Thread):
    def __init__(
        self,
        cam_cfg: dict,
        *,
        camera,
        tracker,
        pose,
        zone_manager,
        alert_manager,
        face_recognizer,
        emotion_detector,
        threat_assessor,
        anomaly_detector,
        night_vision,
        recorder,
        predictor,
        db,
        settings,
        registry=None,
        ear_fn: Callable | None = None,
        on_incident_updated: Callable[[int], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(name=f"worker-{cam_cfg['id']}", daemon=True)
        self.camera_id = str(cam_cfg["id"])
        self.camera_name = str(cam_cfg.get("name") or self.camera_id.upper())
        self.camera = camera
        self.tracker = tracker
        self.pose = pose
        self.zone_manager = zone_manager
        self.alert_manager = alert_manager
        self.face_recognizer = face_recognizer
        self.emotion_detector = emotion_detector
        self.threat_assessor = threat_assessor
        self.anomaly_detector = anomaly_detector
        self.night_vision = night_vision
        self.recorder = recorder
        self.predictor = predictor
        self.db = db
        self.settings = settings
        self.on_incident_updated = on_incident_updated
        self.clock = clock

        if registry is None:
            from src.engine.track_state import TrackRegistry
            from src.liveness_detector import BlinkTracker

            registry = TrackRegistry(blink_factory=lambda: BlinkTracker(settings.EAR_THRESHOLD, settings.LIVENESS_TTL))
        self.registry = registry
        if ear_fn is None:
            from src.liveness_detector import ear_from_landmarks

            ear_fn = ear_from_landmarks
        self.ear_fn = ear_fn

        self.frame_w = int(settings.FRAME_WIDTH)
        self.frame_h = int(settings.FRAME_HEIGHT)
        self._stop_event = threading.Event()  # not `_stop`: Thread.join() calls self._stop()
        self._cond = threading.Condition()
        self._jpeg: bytes = self._placeholder("STARTING")
        self._clean: np.ndarray | None = None
        self._seq = 0
        self._fps = 0.0
        self._last_frame_at: float | None = None
        self._night = False
        self._frame_count = 0
        self._last_pose: list = []
        self._posture_seen: dict[int, float] = {}
        self._last_prune = 0.0
        self._errors = _RateLimitedLog()

    # ------------------------------------------------------------------ public
    def latest_jpeg(self, annotated: bool = True) -> bytes:
        with self._cond:
            if annotated or self._clean is None:
                return self._jpeg
            clean = self._clean
        ok, buf = cv2.imencode(".jpg", clean, [int(cv2.IMWRITE_JPEG_QUALITY), int(self.settings.JPEG_QUALITY)])
        return buf.tobytes() if ok else self._jpeg

    def wait_for_frame(self, last_seq: int, timeout: float = 1.0) -> tuple[int, bytes]:
        with self._cond:
            if self._seq <= last_seq:
                self._cond.wait_for(lambda: self._seq > last_seq or self._stop_event.is_set(), timeout=timeout)
            return self._seq, self._jpeg

    def status(self) -> dict:
        last = self._last_frame_at
        return {
            "id": self.camera_id,
            "name": self.camera_name,
            "online": bool(self.camera.online),
            "fps": round(self._fps, 1),
            "tracks": len(self.registry),
            "night_mode": self._night,
            "last_frame_at": datetime.fromtimestamp(last, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if last else None,
            "source": self.camera.source_label,
        }

    def stop(self) -> None:
        self._stop_event.set()
        with self._cond:
            self._cond.notify_all()
        try:
            self.recorder.flush(self.clock() + 1e9)  # finish any recording immediately
        except Exception:  # noqa: BLE001
            log.exception("recorder flush on stop failed")

    # ------------------------------------------------------------------ loop
    def run(self) -> None:
        last_seq: int | None = None
        while not self._stop_event.is_set():
            try:
                ok, raw, seq = self.camera.read(last_seq, timeout=0.5)
                if not ok:
                    self._go_offline()
                    self._stop_event.wait(0.2)
                    continue
                if raw is None:
                    continue  # timeout without a new frame
                last_seq = seq
                self._process(raw)
            except Exception:  # noqa: BLE001
                self._errors.exception("loop", "camera %s iteration failed", self.camera_id)
                self._stop_event.wait(0.05)

    def _go_offline(self) -> None:
        with self._cond:
            self._jpeg = self._placeholder(f"{self.camera_name} OFFLINE")
            self._seq += 1
            self._cond.notify_all()
        try:
            self.recorder.flush(self.clock())
        except Exception:  # noqa: BLE001
            self._errors.exception("flush", "recorder flush failed")

    def process_frame(self, raw: np.ndarray) -> None:
        """Run the full per-frame pipeline on one raw frame, synchronously.

        The camera thread calls this through ``run``; the evaluation harness
        (``tools/replay.py``) calls it directly with an injected clock so a clip
        can be replayed deterministically at any speed.
        """
        self._process(raw)

    def _process(self, raw: np.ndarray) -> None:
        now = self.clock()
        s = self.settings
        raw_h, raw_w = raw.shape[:2]
        clean = raw if (raw_w, raw_h) == (self.frame_w, self.frame_h) else cv2.resize(raw, (self.frame_w, self.frame_h))
        sx, sy = raw_w / self.frame_w, raw_h / self.frame_h
        self._frame_count += 1

        self._night = bool(self.night_vision.is_low_light(clean))
        if self._night:
            clean = self.night_vision.enhance(clean)

        if self._frame_count % max(1, int(s.POSE_EVERY_N_FRAMES)) == 0 or not self._last_pose:
            self._last_pose = self.pose.estimate(clean)
        people = self._last_pose

        detections = self.tracker.track(clean)
        active_ids = []
        for det in detections:
            track = self.registry.get_or_create(
                det.track_id, det.class_id, s.THREAT_CLASSES.get(det.class_id, "Object"), now
            )
            active_ids.append(det.track_id)
            self._update_track(track, det, clean, raw, (sx, sy), people, now)

        self.recorder.update(clean, now)
        self._publish(self._annotate(clean, now), clean, now)
        if now - self._last_prune >= PRUNE_INTERVAL:
            self._last_prune = now
            self._prune(now)

    # ------------------------------------------------------------------ per track
    def _update_track(self, track, det, clean, raw, scale, people, now: float) -> None:
        s = self.settings
        x1, y1, x2, y2 = det.bbox
        prev_bbox = track.bbox
        track.bbox = det.bbox
        track.has_weapon = det.class_id == WEAPON_CLASS

        foot = (min(max((x1 + x2) // 2, 0), self.frame_w - 1), min(max(y2, 0), self.frame_h - 1))
        level = self.zone_manager.level_at(self.camera_id, foot[0], foot[1], self.frame_w, self.frame_h)
        if level != track.zone_level or track.zone_entered_at is None:
            track.zone_level = level
            track.zone_entered_at = now

        self._update_posture(track, det.bbox, people, now)
        self.predictor.update(track.track_id, (x1 + x2) / 2, (y1 + y2) / 2)

        if track.is_person:
            track.is_anomaly, track.anomaly_type, _ = self.anomaly_detector.analyze(
                track.track_id, det.bbox, ((x1 + x2) / 2, (y1 + y2) / 2), now
            )
            self._sample_blink(track, det.bbox, prev_bbox, raw, scale, now)
            heavy_due = (self._frame_count - track.last_heavy_frame) >= int(s.HEAVY_EVERY_N_FRAMES)
            if heavy_due:
                track.last_heavy_frame = self._frame_count
                try:
                    self._heavy(track, det.bbox, raw, scale, now)
                except Exception:  # noqa: BLE001
                    self._errors.exception("heavy", "face/emotion analysis failed on %s", self.camera_id)

        track.update_face_status(now, float(s.LIVENESS_GRACE), float(s.LIVENESS_MAX_VERIFY))
        is_crawling = (
            track.posture == "PRONE"
            and track.posture_since is not None
            and now - track.posture_since >= float(s.PRONE_MIN_SECONDS)
        )
        score, category, reasons = self.threat_assessor.calculate_threat(
            zone_level=track.zone_level,
            object_type=track.obj_type,
            face_status=track.face_status,
            is_anomaly=track.is_anomaly,
            is_crawling=is_crawling,
            has_weapon=track.has_weapon,
            loiter_seconds=track.loiter_seconds(now),
            anomaly_type=track.anomaly_type,
        )
        track.score, track.category, track.reasons = int(score), category, list(reasons)

        incident_id = self.alert_manager.consider(
            camera_id=self.camera_id, camera_name=self.camera_name, track=track, frame=clean, now=now
        )
        if incident_id is not None:
            # Bind the id by value: a lambda over the loop variable would see a
            # later iteration's value when the writer thread fires seconds later.
            self.recorder.trigger(
                f"incident_{incident_id}", on_saved=functools.partial(self._on_clip_saved, incident_id)
            )

    def _update_posture(self, track, bbox, people, now: float) -> None:
        person = match_pose_to_bbox(bbox, people) if track.is_person else None
        posture = posture_from_keypoints(person.keypoints, bbox) if person is not None else "UNKNOWN"
        if posture == "UNKNOWN":
            last_seen = self._posture_seen.get(track.track_id)
            if track.posture != "UNKNOWN" and last_seen is not None and now - last_seen <= POSTURE_UNKNOWN_TOLERANCE:
                return  # brief keypoint loss: keep the current posture and its timer
            track.posture, track.posture_since = "UNKNOWN", None
            return
        self._posture_seen[track.track_id] = now
        if posture != track.posture:
            track.posture, track.posture_since = posture, now

    def _sample_blink(self, track, bbox, prev_bbox, raw, scale, now: float) -> None:
        if track.identity == "Unknown" or track.face_bbox is None or track.face_seen_at is None:
            return
        if now - track.face_seen_at > FACE_BBOX_MAX_AGE:
            return
        sx, sy = scale
        fx1, fy1, fx2, fy2 = track.face_bbox
        if track.face_anchor is not None:
            ax1, ay1, ax2, ay2 = track.face_anchor
            dx = ((bbox[0] + bbox[2]) / 2 - (ax1 + ax2) / 2) * sx
            dy = (bbox[1] - ay1) * sy
            fx1, fx2, fy1, fy2 = fx1 + dx, fx2 + dx, fy1 + dy, fy2 + dy
        landmarks = self.face_recognizer.landmarks_at(raw, (int(fx1), int(fy1), int(fx2), int(fy2)))
        track.blink.update(self.ear_fn(landmarks), now)

    def _heavy(self, track, bbox, raw, scale, now: float) -> None:
        sx, sy = scale
        scaled = (int(bbox[0] * sx), int(bbox[1] * sy), int(bbox[2] * sx), int(bbox[3] * sy))
        result = self.face_recognizer.analyze(raw, scaled)
        if not result.found:
            track.face_bbox = None
            return
        track.vote_identity(result.name)
        track.face_bbox = result.face_bbox
        track.face_anchor = bbox
        track.face_seen_at = now
        if result.landmarks:
            track.blink.update(self.ear_fn(result.landmarks), now)
            emotion = self.emotion_detector.classify(result.landmarks)
            track.emotion = emotion.get("emotion", "N/A")
            track.emotion_confidence = int(emotion.get("confidence", 0))

    def _on_clip_saved(self, incident_id: int, path: str) -> None:
        try:
            self.db.set_clip_path(incident_id, path)
            if self.on_incident_updated is not None:
                self.on_incident_updated(incident_id)
        except Exception:  # noqa: BLE001
            log.exception("could not attach clip to incident %s", incident_id)

    def _prune(self, now: float) -> None:
        stale = self.registry.prune(now, float(self.settings.TRACK_MAX_AGE))
        active = [t.track_id for t in self.registry.active()]
        if stale:
            self.alert_manager.forget(self.camera_id, stale)
            for tid in stale:
                self._posture_seen.pop(tid, None)
        self.anomaly_detector.prune(active)
        self.predictor.prune(active)

    # ------------------------------------------------------------------ output
    def _annotate(self, clean: np.ndarray, now: float) -> np.ndarray:
        frame = clean.copy()
        self.zone_manager.draw(frame, self.camera_id)
        if self._last_pose:
            self.pose.draw(frame, self._last_pose)
        for track in self.registry.active():
            if now - track.last_seen > 0.5:
                continue
            x1, y1, x2, y2 = (int(v) for v in track.bbox)
            colour = (0, 255, 0) if track.is_authorized else ((0, 0, 255) if track.score >= 70 else (0, 165, 255))
            cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
            label = _label(track)
            cv2.putText(frame, label, (x1, max(y1 - 8, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 2)
            if track.is_person:
                nxt = self.predictor.predict_next_position(track.track_id)
                if nxt is not None:
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    cv2.arrowedLine(frame, (cx, cy), nxt, (255, 255, 0), 2, tipLength=0.3)
        header = f"{self.camera_name} {datetime.now(UTC).strftime('%H:%M:%S')}Z"
        if self._night:
            header += " NIGHT"
        cv2.putText(frame, header, (10, self.frame_h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        return frame

    def _publish(self, annotated: np.ndarray, clean: np.ndarray, now: float) -> None:
        ok, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), int(self.settings.JPEG_QUALITY)])
        if not ok:
            return
        with self._cond:
            if self._last_frame_at is not None:
                dt = now - self._last_frame_at
                if dt > 0:
                    inst = 1.0 / dt
                    self._fps = inst if self._fps == 0 else 0.9 * self._fps + 0.1 * inst
            self._last_frame_at = now
            self._jpeg = buf.tobytes()
            self._clean = clean
            self._seq += 1
            self._cond.notify_all()

    def _placeholder(self, text: str) -> bytes:
        img = np.zeros((self.frame_h, self.frame_w, 3), dtype=np.uint8)
        cv2.putText(img, text, (40, self.frame_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        cv2.putText(
            img, "waiting for frames", (40, self.frame_h // 2 + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 1
        )
        ok, buf = cv2.imencode(".jpg", img)
        return buf.tobytes() if ok else b""


def _label(track) -> str:
    """ASCII-only label: OpenCV cannot render emoji."""
    if track.has_weapon:
        prefix = "LETHAL"
    elif track.is_authorized:
        prefix = "AUTH"
    elif track.face_status == "SPOOF":
        prefix = "SPOOF"
    elif track.face_status == "VERIFYING":
        prefix = "VERIFY"
    else:
        prefix = "WARN"
    name = track.identity if track.identity != "Unknown" else track.obj_type
    parts = [prefix, f"#{track.track_id}", name, f"{track.score}%"]
    if track.is_person and track.emotion not in ("N/A", "Unknown"):
        parts.append(track.emotion)
    if track.posture == "PRONE":
        parts.append("PRONE")
    return " ".join(parts)
