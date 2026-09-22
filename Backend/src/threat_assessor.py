"""Rule-based threat scoring. Pure: no I/O, no state beyond configuration."""

from __future__ import annotations

MIN_SCORE = 0
MAX_SCORE = 100

_ZONE_RULES = {
    "CRITICAL": (40, "Breached Critical Zone"),
    "WARNING": (30, "In Warning Zone"),
    "PERIMETER": (20, "In Perimeter"),
    "SAFE": (0, "In Safe Zone"),
}
_OBJECT_RULES = {
    "Person": (30, None),
    "Car": (40, "Vehicle Detected"),
    "Motorcycle": (40, "Vehicle Detected"),
    "Dog": (10, "Animal Detected"),
}
_FACE_RULES = {
    "KNOWN": (-50, "Authorized Personnel"),
    "SPOOF": (50, "Spoofing Attempt Detected"),
    # Liveness is still being established: neither trusted nor penalised yet.
    "VERIFYING": (0, "Verifying liveness"),
    "N/A": (0, None),
}
_UNKNOWN_FACE_RULE = (20, "Unknown Identity")

WEAPON_REASON = "CRITICAL: Lethal Weapon Detected!"
CRAWLING_SCORE = 50
ANOMALY_SCORE = 40
LOITERING_SCORE = 20


def categorize(score: int) -> str:
    """<30 LOW (log only), <70 WARNING, else CRITICAL (alert + record)."""
    if score < 30:
        return "LOW"
    if score < 70:
        return "WARNING"
    return "CRITICAL"


class ThreatAssessor:
    """Combines zone, object class, identity and behaviour into a 0-100 score."""

    def __init__(self, loiter_threshold: float | None = None):
        """``loiter_threshold`` None resolves to ``settings.LOITER_SECONDS``.

        Resolved here rather than per call so ``calculate_threat`` stays pure.
        """
        if loiter_threshold is None:
            from config import settings

            loiter_threshold = settings.LOITER_SECONDS
        self.loiter_threshold = float(loiter_threshold)

    def calculate_threat(
        self,
        zone_level,
        object_type,
        face_status="UNKNOWN",
        is_anomaly=False,
        is_crawling=False,
        has_weapon=False,
        loiter_seconds=0.0,
        anomaly_type=None,
        loiter_threshold=None,
    ) -> tuple[int, str, list[str]]:
        """Return ``(score, category, reasons)``.

        ``face_status`` only matters for persons. ``loiter_threshold`` None
        uses the assessor's configured threshold; a threshold <= 0 disables
        the loitering rule.
        """
        if has_weapon:
            # A weapon overrides every mitigating factor, identity included.
            return MAX_SCORE, "CRITICAL", [WEAPON_REASON]

        score = 0
        reasons: list[str] = []

        def apply(rule: tuple[int, str | None]) -> None:
            nonlocal score
            points, reason = rule
            score += points
            if reason:
                reasons.append(reason)

        apply(_ZONE_RULES.get(zone_level, (0, None)))
        apply(_OBJECT_RULES.get(object_type, (0, None)))
        if object_type == "Person":
            apply(_FACE_RULES.get(face_status, _UNKNOWN_FACE_RULE))
        if is_crawling:
            apply((CRAWLING_SCORE, "Suspicious Posture: Crawling/Prone"))
        if is_anomaly:
            label = f"Anomalous Behavior: {anomaly_type}" if anomaly_type else "Anomalous/Suspicious Behavior"
            apply((ANOMALY_SCORE, label))

        threshold = self.loiter_threshold if loiter_threshold is None else loiter_threshold
        # A verified resident standing in their own yard is not loitering.
        if threshold > 0 and loiter_seconds >= threshold and zone_level != "SAFE" and face_status != "KNOWN":
            apply((LOITERING_SCORE, f"Loitering {int(loiter_seconds)}s"))

        final_score = max(MIN_SCORE, min(MAX_SCORE, score))
        return final_score, categorize(final_score), reasons
