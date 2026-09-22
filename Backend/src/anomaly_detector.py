"""Per-track motion anomaly detection (one detector per camera worker).

The v1 detector compared raw *pixels per call* against fixed thresholds, so
the verdict depended on how often ``analyze`` was invoked and on how far the
person stood from the camera: a normal walk sampled every 5th frame looked
like sprinting, and a person near the lens "ran" faster than one far away.

Speeds here are body-heights per second: the pixel displacement between two
samples is divided by the elapsed time AND by the person's bounding-box
height. The same physical motion therefore produces the same verdict at 6 FPS
and 30 FPS and at any distance from the camera. The bbox-aspect "crawling"
rule was removed; posture now comes from pose keypoints (``engine.posture``).
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

log = logging.getLogger("chanakya.anomaly_detector")

RUNNING = "RUNNING"
ERRATIC = "ERRATIC"

SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"

NO_ANOMALY: tuple[bool, None, None] = (False, None, None)


@dataclass
class _TrackHistory:
    """Speed samples for one track, plus the previous position for deltas."""

    last_t: float
    last_pos: tuple[float, float]
    speeds: deque[float]
    times: deque[float]
    first_sample_t: float | None = None
    samples: int = field(default=0)


class AnomalyDetector:
    """Flags RUNNING / ERRATIC movement from scale- and time-normalised speed.

    ``run_speed`` and ``erratic_speed`` are body-heights per second; ``None``
    resolves them from ``config.settings`` inside ``__init__`` (never at
    import). ``window`` is the number of most recent speed samples the
    verdict is computed over; ``min_samples`` / ``min_span_s`` gate how much
    evidence is needed before any verdict is returned.
    """

    def __init__(
        self,
        run_speed: float | None = None,
        erratic_speed: float | None = None,
        *,
        window: int = 10,
        min_samples: int = 10,
        min_span_s: float = 2.0,
        max_dt: float = 1.0,
        history: int = 60,
    ) -> None:
        if run_speed is None or erratic_speed is None:
            from config import settings

            if run_speed is None:
                run_speed = float(settings.RUN_SPEED_BH)
            if erratic_speed is None:
                erratic_speed = float(settings.ERRATIC_SPEED_BH)
        self.run_speed = float(run_speed)
        self.erratic_speed = float(erratic_speed)
        self.window = max(1, int(window))
        self.min_samples = max(1, int(min_samples))
        self.min_span_s = float(min_span_s)
        self.max_dt = float(max_dt)
        self.history_len = max(self.window, int(history))
        self._tracks: dict[int, _TrackHistory] = {}

    # ------------------------------------------------------------------ API
    def analyze(
        self,
        person_id: int,
        bbox: tuple[float, float, float, float],
        position: tuple[float, float],
        now: float | None = None,
    ) -> tuple[bool, str | None, str | None]:
        """Record one sample and return ``(is_anomaly, anomaly_type, severity)``.

        Called every processed frame per person track. ``position`` is the
        point whose displacement is measured (the worker passes the bbox
        centre); ``bbox`` supplies the height used for scale normalisation.
        Samples with ``dt <= 0`` (duplicate/out-of-order timestamps) or
        ``dt > max_dt`` (the track vanished and re-appeared) are skipped: a
        big jump after a long gap is a tracking artefact, not a sprint.
        """
        t = time.time() if now is None else float(now)
        x, y = float(position[0]), float(position[1])
        hist = self._tracks.get(person_id)
        if hist is None:
            self._tracks[person_id] = _TrackHistory(
                last_t=t,
                last_pos=(x, y),
                speeds=deque(maxlen=self.history_len),
                times=deque(maxlen=self.history_len),
            )
            return NO_ANOMALY

        dt = t - hist.last_t
        prev_x, prev_y = hist.last_pos
        hist.last_t = t
        hist.last_pos = (x, y)
        if dt <= 0.0 or dt > self.max_dt:
            return self._verdict(hist)

        bbox_h = max(float(bbox[3]) - float(bbox[1]), 1.0)
        pixels = math.hypot(x - prev_x, y - prev_y)
        speed = pixels / dt / bbox_h
        if hist.first_sample_t is None:
            hist.first_sample_t = hist.last_t - dt
        hist.speeds.append(speed)
        hist.times.append(t)
        hist.samples += 1
        return self._verdict(hist)

    def prune(self, active_ids: Iterable[int]) -> None:
        """Drop history for tracks that are no longer active."""
        keep = set(active_ids)
        for pid in [pid for pid in self._tracks if pid not in keep]:
            del self._tracks[pid]

    def reset_person(self, person_id: int) -> None:
        """Forget a single track (legacy name kept for callers)."""
        self._tracks.pop(person_id, None)

    def __len__(self) -> int:
        return len(self._tracks)

    # ------------------------------------------------------------- internals
    def _verdict(self, hist: _TrackHistory) -> tuple[bool, str | None, str | None]:
        if len(hist.speeds) < self.min_samples:
            return NO_ANOMALY
        if hist.first_sample_t is None or hist.times[-1] - hist.first_sample_t < self.min_span_s:
            return NO_ANOMALY
        recent = list(hist.speeds)[-self.window :]
        mean = sum(recent) / len(recent)
        if mean > self.run_speed:
            return True, RUNNING, SEVERITY_HIGH
        variance = sum((s - mean) ** 2 for s in recent) / len(recent)
        if math.sqrt(variance) > self.erratic_speed:
            return True, ERRATIC, SEVERITY_MEDIUM
        return NO_ANOMALY
