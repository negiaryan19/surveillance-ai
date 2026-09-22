"""Turns per-track threat state into incidents, events and notifications.

One AlertManager is shared by every camera worker. It decides *whether* a
track deserves a new incident (dedup per track, cooldown, escalation,
per-camera spacing), writes the snapshot + DB row, publishes the incident on
the event bus, and rate-limits the external notifier separately so a busy
scene cannot flood Telegram while the incident log stays complete.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("chanakya.alert_manager")


@dataclass
class _TrackAlert:
    last_at: float
    last_score: int


class AlertManager:
    def __init__(
        self,
        db,
        event_bus,
        *,
        notifier: Callable | None = None,
        snapshot_writer: Callable | None = None,
        snapshots_dir=None,
        serializer: Callable[[dict], dict] | None = None,
        min_score: int | None = None,
        min_track_age: float | None = None,
        track_cooldown: float | None = None,
        escalation_delta: int | None = None,
        camera_min_interval: float | None = None,
        notify_min_interval: float | None = None,
        weapon_min_hits: int | None = None,
        weapon_alert_interval: float | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        from config import settings

        self.db = db
        self.event_bus = event_bus
        self._notifier = notifier
        self._snapshot_writer = snapshot_writer
        self.snapshots_dir = Path(snapshots_dir if snapshots_dir is not None else settings.SNAPSHOTS_DIR)
        self.serializer = serializer or (lambda d: d)
        self.min_score = int(settings.ALERT_MIN_SCORE if min_score is None else min_score)
        self.min_track_age = float(settings.ALERT_MIN_TRACK_AGE if min_track_age is None else min_track_age)
        self.track_cooldown = float(settings.ALERT_TRACK_COOLDOWN if track_cooldown is None else track_cooldown)
        self.escalation_delta = int(settings.ALERT_ESCALATION_DELTA if escalation_delta is None else escalation_delta)
        self.camera_min_interval = float(
            settings.ALERT_CAMERA_MIN_INTERVAL if camera_min_interval is None else camera_min_interval
        )
        self.notify_min_interval = float(
            settings.ALERT_NOTIFY_MIN_INTERVAL if notify_min_interval is None else notify_min_interval
        )
        self.weapon_min_hits = int(settings.WEAPON_MIN_HITS if weapon_min_hits is None else weapon_min_hits)
        self.weapon_alert_interval = float(
            settings.WEAPON_ALERT_INTERVAL if weapon_alert_interval is None else weapon_alert_interval
        )
        self.clock = clock

        self._lock = threading.Lock()
        self._paused = False
        self._per_track: dict[tuple[str, int], _TrackAlert] = {}
        self._camera_last: dict[str, float] = {}
        self._camera_last_weapon: dict[str, float] = {}
        self._notified: dict[str, _TrackAlert] = {}

    # ------------------------------------------------------------- controls
    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def forget(self, camera_id: str, track_ids: Iterable[int]) -> None:
        with self._lock:
            for tid in track_ids:
                self._per_track.pop((camera_id, int(tid)), None)

    # ------------------------------------------------------------- decision
    def consider(self, *, camera_id: str, camera_name: str, track, frame, now: float | None = None) -> int | None:
        """Return a new incident id when this track warrants an alert now."""
        now = self.clock() if now is None else float(now)
        with self._lock:
            if not self._should_alert(camera_id, track, now):
                return None
            # Reserve the slot inside the lock so two workers cannot both pass
            # the per-camera spacing check at the same instant.
            key = (camera_id, int(track.track_id))
            self._per_track[key] = _TrackAlert(last_at=now, last_score=int(track.score))
            if track.has_weapon:
                self._camera_last_weapon[camera_id] = now
            else:
                self._camera_last[camera_id] = now
            paused = self._paused
            notify = (not paused) and self._should_notify(camera_id, track, now)

        image_path = self._write_snapshot(camera_id, track, frame, now)
        incident_id = self.db.log_incident(
            camera=camera_id,
            object_type=track.obj_type,
            threat_score=int(track.score),
            zone_level=track.zone_level,
            category=track.category,
            track_id=int(track.track_id),
            identity=None if track.identity == "Unknown" else track.identity,
            emotion=None if track.emotion in ("N/A", "Unknown") else track.emotion,
            reasons=list(track.reasons),
            image_path=image_path,
        )
        try:
            self.event_bus.publish("incident", self.serializer(self.db.get_incident(incident_id)))
        except Exception:  # noqa: BLE001 - never let a bad subscriber stall the worker
            log.exception("publishing incident %s failed", incident_id)

        if notify:
            self._notify(camera_name, track, image_path)
        return incident_id

    def _should_alert(self, camera_id: str, track, now: float) -> bool:
        if track.score < self.min_score or track.is_authorized:
            return False
        if not track.has_weapon and (now - track.first_seen) < self.min_track_age:
            return False  # let a few face analyses run before an identity-based alert
        if track.has_weapon and track.hits < self.weapon_min_hits:
            return False  # a knife box must persist; single-frame flickers are phones and pens
        if track.face_status == "VERIFYING" and not track.has_weapon:
            return False

        key = (camera_id, int(track.track_id))
        prev = self._per_track.get(key)
        if prev is not None:
            cooled = (now - prev.last_at) >= self.track_cooldown
            escalated = track.score >= prev.last_score + self.escalation_delta
            if not (cooled or escalated):
                return False

        if track.has_weapon:
            last = self._camera_last_weapon.get(camera_id)
            return last is None or (now - last) >= self.weapon_alert_interval
        last = self._camera_last.get(camera_id)
        return last is None or (now - last) >= self.camera_min_interval

    def _should_notify(self, camera_id: str, track, now: float) -> bool:
        prev = self._notified.get(camera_id)
        if track.has_weapon or prev is None or (now - prev.last_at) >= self.notify_min_interval:
            ok = True
        else:
            ok = track.score >= prev.last_score + self.escalation_delta
        if ok:
            self._notified[camera_id] = _TrackAlert(last_at=now, last_score=int(track.score))
        return ok

    # ------------------------------------------------------------- side effects
    def _write_snapshot(self, camera_id: str, track, frame, now: float) -> str | None:
        if frame is None:
            return None
        try:
            self.snapshots_dir.mkdir(parents=True, exist_ok=True)
            path = self.snapshots_dir / f"alert_{camera_id}_{int(track.track_id)}_{int(now * 1000)}.jpg"
            image = self._annotate(frame, track)
            writer = self._snapshot_writer or _cv2_imwrite
            if writer(str(path), image):
                return str(path.resolve())
            log.warning("snapshot writer refused %s", path.name)
        except Exception:  # noqa: BLE001
            log.exception("snapshot failed for %s track %s", camera_id, track.track_id)
        return None

    @staticmethod
    def _annotate(frame, track):
        try:
            import cv2

            image = frame.copy()
            x1, y1, x2, y2 = (int(v) for v in track.bbox)
            colour = (0, 0, 255) if track.score >= 70 else (0, 165, 255)
            cv2.rectangle(image, (x1, y1), (x2, y2), colour, 2)
            cv2.putText(
                image,
                f"{track.obj_type} {track.score}%",
                (x1, max(y1 - 8, 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                colour,
                2,
            )
            return image
        except Exception:  # noqa: BLE001 - cv2 missing in tests, or an odd frame type
            return frame

    def _notify(self, camera_name: str, track, image_path: str | None) -> None:
        notifier = self._notifier
        if notifier is None:
            from src.telegram_bot import send_telegram_alert

            notifier = send_telegram_alert
        subject = (
            f"{track.identity if track.identity != 'Unknown' else track.obj_type} ID:{track.track_id} ({camera_name})"
        )
        extra = ", ".join(track.reasons) if track.reasons else None
        try:
            notifier(subject, int(track.score), image_path, extra)
        except Exception:  # noqa: BLE001
            log.exception("notifier failed")


def _cv2_imwrite(path: str, image) -> bool:
    import cv2

    return bool(cv2.imwrite(path, image))
