"""Blink-based liveness, tracked per person.

v1 kept ONE global ``is_live`` flag that latched True forever after anybody's
first blink, so a printed photo held up after a real person had been seen was
"live". Here every track owns a :class:`BlinkTracker`; a blink is only
credited when the eye-aspect-ratio (EAR) trace has the shape of a real blink,
and liveness expires after ``ttl`` seconds so it has to be re-proven.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = Sequence[float]


def eye_aspect_ratio(eye: Sequence[Point]) -> float:
    """EAR from the six dlib eye landmarks; 0.0 when degenerate."""
    if len(eye) < 6:
        return 0.0
    v1 = math.dist(eye[1], eye[5])
    v2 = math.dist(eye[2], eye[4])
    h = math.dist(eye[0], eye[3])
    if h <= 0:
        return 0.0
    return (v1 + v2) / (2.0 * h)


def ear_from_landmarks(landmarks: dict | None) -> float | None:
    """Mean EAR of both eyes, or None when either eye is missing."""
    if not landmarks:
        return None
    left = landmarks.get("left_eye")
    right = landmarks.get("right_eye")
    if not left or not right:
        return None
    l_ear = eye_aspect_ratio(left)
    r_ear = eye_aspect_ratio(right)
    if l_ear <= 0 or r_ear <= 0:
        return None
    return (l_ear + r_ear) / 2.0


class BlinkTracker:
    """Blink detector for ONE track.

    A blink is a run of samples with ``ear < ear_thresh`` that
      (a) lasts at most ``max_blink_s`` (longer closures are garbage landmarks
          or a photo held at an angle, not a blink),
      (b) is preceded by at least two samples clearly open
          (``ear >= ear_thresh + open_margin``), and
      (c) is ended by a sample at or above ``ear_thresh``.

    ``observed_s`` accumulates seconds of *continuous* valid observation since
    the last blink; the track state machine uses it to decide that a face was
    watched long enough without blinking to be called a spoof. It resets when
    a blink completes and when observation was interrupted for more than
    ``gap_reset_s`` — absence of observation is never evidence of spoofing.
    """

    def __init__(
        self,
        ear_thresh: float = 0.22,
        ttl: float = 30.0,
        max_blink_s: float = 0.8,
        gap_reset_s: float = 1.0,
        open_margin: float = 0.03,
    ) -> None:
        self.ear_thresh = float(ear_thresh)
        self.ttl = float(ttl)
        self.max_blink_s = float(max_blink_s)
        self.gap_reset_s = float(gap_reset_s)
        self.open_margin = float(open_margin)

        self.blinks = 0
        self.last_blink_at: float | None = None
        self.observed_s = 0.0

        self._open_streak = 0  # consecutive clearly-open samples before a closure
        self._closed_since: float | None = None
        self._closed_valid = False  # closure started after a proper open preamble
        self._last_sample_at: float | None = None

    def update(self, ear: float | None, now: float) -> bool:
        """Feed one sample; return True when a blink has just completed."""
        if ear is None:
            return False
        now = float(now)
        if self._last_sample_at is not None:
            gap = now - self._last_sample_at
            if gap > self.gap_reset_s:
                # Observation was interrupted: restart the continuous window
                # and forget any half-seen closure.
                self.observed_s = 0.0
                self._open_streak = 0
                self._closed_since = None
                self._closed_valid = False
            else:
                self.observed_s += min(max(gap, 0.0), 0.5)
        self._last_sample_at = now

        completed = False
        if ear < self.ear_thresh:
            if self._closed_since is None:
                self._closed_since = now
                self._closed_valid = self._open_streak >= 2
            self._open_streak = 0
        else:
            if self._closed_since is not None:
                closed_for = now - self._closed_since
                if self._closed_valid and closed_for <= self.max_blink_s:
                    completed = True
                self._closed_since = None
                self._closed_valid = False
            if ear >= self.ear_thresh + self.open_margin:
                self._open_streak += 1
            else:
                self._open_streak = 0

        if completed:
            self.blinks += 1
            self.last_blink_at = now
            self.observed_s = 0.0
        return completed

    def is_live(self, now: float) -> bool:
        """True when a blink completed within the last ``ttl`` seconds."""
        return self.last_blink_at is not None and (float(now) - self.last_blink_at) <= self.ttl


class LivenessDetector:
    """Factory for per-track :class:`BlinkTracker` objects using project settings."""

    def __init__(self, ear_thresh: float | None = None, ttl: float | None = None) -> None:
        if ear_thresh is None or ttl is None:
            from config import settings

            if ear_thresh is None:
                ear_thresh = settings.EAR_THRESHOLD
            if ttl is None:
                ttl = settings.LIVENESS_TTL
        self.ear_thresh = float(ear_thresh)
        self.ttl = float(ttl)

    def new_tracker(self) -> BlinkTracker:
        return BlinkTracker(ear_thresh=self.ear_thresh, ttl=self.ttl)
