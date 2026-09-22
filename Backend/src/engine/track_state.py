"""Per-track state carried across frames, and the registry that owns it.

The camera worker does cheap work every frame and expensive work (face
recognition, emotion) every N frames; everything it learns lives here so the
threat score and the alert decision can be computed every frame from the last
known facts.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field

from src.liveness_detector import BlinkTracker

FACE_STATUSES = ("KNOWN", "SPOOF", "VERIFYING", "UNKNOWN", "N/A")
IDENTITY_VOTES = 5


@dataclass
class TrackState:
    track_id: int
    class_id: int
    obj_type: str
    first_seen: float
    last_seen: float
    blink: BlinkTracker
    hits: int = 0

    identity: str = "Unknown"
    face_status: str = "UNKNOWN"
    is_authorized: bool = False
    verified_once: bool = False
    verify_started_at: float | None = None
    face_bbox: tuple | None = None
    face_anchor: tuple | None = None
    face_seen_at: float | None = None

    emotion: str = "N/A"
    emotion_confidence: int = 0

    posture: str = "UNKNOWN"
    posture_since: float | None = None

    is_anomaly: bool = False
    anomaly_type: str | None = None

    zone_level: str = "SAFE"
    zone_entered_at: float | None = None

    score: int = 0
    category: str = "LOW"
    reasons: list[str] = field(default_factory=list)

    has_weapon: bool = False
    bbox: tuple = (0, 0, 0, 0)
    last_heavy_frame: int = -(10**9)

    _votes: deque[str] = field(default_factory=lambda: deque(maxlen=IDENTITY_VOTES), repr=False)

    @property
    def is_person(self) -> bool:
        return self.class_id == 0

    def vote_identity(self, name: str) -> str:
        """Record one identity vote from an analysis that FOUND a face.

        Analyses that saw no face must not vote: a known person turning away
        would otherwise flip to Unknown within seconds and trigger an alert.
        Majority over the last few votes smooths single-frame mismatches.
        """
        self._votes.append(name or "Unknown")
        counts = Counter(self._votes)
        top, n = counts.most_common(1)[0]
        # Require a strict majority so a single early vote does not decide.
        winner = top if n * 2 > len(self._votes) else self.identity
        if winner != self.identity:
            self.identity = winner
            self.verify_started_at = None
            self.verified_once = False
        return self.identity

    def update_face_status(self, now: float, grace: float, max_verify: float) -> str:
        """Derive face_status from identity + liveness. Rule order matters.

        SPOOF is only asserted after a face has been continuously watched for
        ``grace`` seconds without a blink. A track that already proved itself
        live stays KNOWN when liveness lapses unobserved — the absence of
        observation is not evidence of spoofing.
        """
        if not self.is_person:
            status = "N/A"
        elif self.identity == "Unknown":
            status = "UNKNOWN"
            self.verify_started_at = None
        elif self.blink.is_live(now):
            status = "KNOWN"
            self.verified_once = True
            self.verify_started_at = None
        elif self.blink.observed_s >= grace:
            status = "SPOOF"
        elif self.verified_once:
            status = "KNOWN"
        else:
            if self.verify_started_at is None:
                self.verify_started_at = now
            status = "VERIFYING" if (now - self.verify_started_at) < max_verify else "UNKNOWN"

        self.face_status = status
        self.is_authorized = status == "KNOWN"
        return status

    def loiter_seconds(self, now: float) -> float:
        if self.zone_level == "SAFE" or self.zone_entered_at is None:
            return 0.0
        return max(0.0, float(now) - self.zone_entered_at)


class TrackRegistry:
    """Owns the TrackState objects of one camera."""

    def __init__(self, blink_factory: Callable[[], BlinkTracker] | None = None) -> None:
        if blink_factory is None:
            from src.liveness_detector import LivenessDetector

            blink_factory = LivenessDetector().new_tracker
        self._blink_factory = blink_factory
        self._tracks: dict[int, TrackState] = {}

    def get_or_create(self, track_id: int, class_id: int, obj_type: str, now: float) -> TrackState:
        track = self._tracks.get(track_id)
        if track is None:
            track = TrackState(
                track_id=track_id,
                class_id=class_id,
                obj_type=obj_type,
                first_seen=now,
                last_seen=now,
                blink=self._blink_factory(),
            )
            self._tracks[track_id] = track
        track.last_seen = now
        track.hits += 1
        return track

    def get(self, track_id: int) -> TrackState | None:
        return self._tracks.get(track_id)

    def prune(self, now: float, max_age: float = 5.0) -> list[int]:
        stale = [tid for tid, t in self._tracks.items() if now - t.last_seen > max_age]
        for tid in stale:
            del self._tracks[tid]
        return stale

    def active(self) -> list[TrackState]:
        return list(self._tracks.values())

    def __len__(self) -> int:
        return len(self._tracks)
