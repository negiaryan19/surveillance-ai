"""src.threat_assessor: every rule in contract §3.5 with explicit numbers.

Weights (unchanged from v1):
  zone   CRITICAL +40 / WARNING +30 / PERIMETER +20 / SAFE +0 (reason only)
  object Person +30 (no reason) / Car, Motorcycle +40 / Dog +10
  face   KNOWN -50 / SPOOF +50 / UNKNOWN +20 / VERIFYING +0 / N/A +0 (persons only)
  crawling +50, anomaly +40, loitering +20, weapon => 100 CRITICAL short-circuit
  clamp 0..100; category <30 LOW, <70 WARNING, else CRITICAL
"""

from __future__ import annotations

import copy

import pytest

from src.threat_assessor import ThreatAssessor, categorize

WEAPON_REASON = "CRITICAL: Lethal Weapon Detected!"


@pytest.fixture
def assessor() -> ThreatAssessor:
    return ThreatAssessor(loiter_threshold=10.0)


# --------------------------------------------------------------------------- #
# construction / settings default
# --------------------------------------------------------------------------- #
def test_default_loiter_threshold_comes_from_settings():
    from config import settings

    assert ThreatAssessor().loiter_threshold == settings.LOITER_SECONDS == 10.0


def test_explicit_loiter_threshold_is_kept():
    assert ThreatAssessor(loiter_threshold=3).loiter_threshold == 3.0


# --------------------------------------------------------------------------- #
# zone rule
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "zone, expected_score, reason",
    [
        ("CRITICAL", 40, "Breached Critical Zone"),
        ("WARNING", 30, "In Warning Zone"),
        ("PERIMETER", 20, "In Perimeter"),
        ("SAFE", 0, "In Safe Zone"),
    ],
)
def test_zone_levels_alone(assessor, zone, expected_score, reason):
    # object "Unknown" adds nothing, so the score isolates the zone weight.
    score, category, reasons = assessor.calculate_threat(zone, "Unknown")
    assert score == expected_score
    assert reasons == [reason]
    assert category == categorize(expected_score)


def test_unrecognised_zone_adds_nothing(assessor):
    assert assessor.calculate_threat("MOON", "Unknown") == (0, "LOW", [])


# --------------------------------------------------------------------------- #
# object rule
# --------------------------------------------------------------------------- #
def test_person_in_safe_zone_unknown_face():
    # Person +30, UNKNOWN +20 => 50 WARNING; Person itself adds no reason
    score, category, reasons = ThreatAssessor(10).calculate_threat("SAFE", "Person")
    assert score == 50
    assert category == "WARNING"
    assert reasons == ["In Safe Zone", "Unknown Identity"]


@pytest.mark.parametrize("vehicle", ["Car", "Motorcycle"])
def test_vehicles_add_40(assessor, vehicle):
    score, category, reasons = assessor.calculate_threat("SAFE", vehicle)
    assert score == 40
    assert category == "WARNING"
    assert reasons == ["In Safe Zone", "Vehicle Detected"]


def test_dog_adds_10(assessor):
    score, category, reasons = assessor.calculate_threat("SAFE", "Dog")
    assert score == 10
    assert category == "LOW"
    assert reasons == ["In Safe Zone", "Animal Detected"]


def test_unknown_object_adds_nothing(assessor):
    score, category, reasons = assessor.calculate_threat("WARNING", "Weapon (Knife)")
    assert score == 30
    assert reasons == ["In Warning Zone"]


def test_face_status_is_ignored_for_non_persons(assessor):
    # A SPOOF/KNOWN label on a Car is meaningless and must not change the score.
    base = assessor.calculate_threat("WARNING", "Car")
    for status in ("KNOWN", "SPOOF", "UNKNOWN", "VERIFYING", "N/A"):
        assert assessor.calculate_threat("WARNING", "Car", face_status=status) == base
    assert base == (70, "CRITICAL", ["In Warning Zone", "Vehicle Detected"])


# --------------------------------------------------------------------------- #
# face rule (persons only)
# --------------------------------------------------------------------------- #
def test_known_face_subtracts_50(assessor):
    # CRITICAL 40 + Person 30 - 50 = 20 LOW
    score, category, reasons = assessor.calculate_threat("CRITICAL", "Person", face_status="KNOWN")
    assert score == 20
    assert category == "LOW"
    assert reasons == ["Breached Critical Zone", "Authorized Personnel"]


def test_spoof_face_adds_50(assessor):
    # SAFE 0 + Person 30 + 50 = 80 CRITICAL
    score, category, reasons = assessor.calculate_threat("SAFE", "Person", face_status="SPOOF")
    assert score == 80
    assert category == "CRITICAL"
    assert reasons == ["In Safe Zone", "Spoofing Attempt Detected"]


def test_unknown_face_adds_20(assessor):
    # PERIMETER 20 + Person 30 + 20 = 70 CRITICAL
    score, category, reasons = assessor.calculate_threat("PERIMETER", "Person", face_status="UNKNOWN")
    assert score == 70
    assert category == "CRITICAL"
    assert reasons == ["In Perimeter", "Unknown Identity"]


def test_face_status_defaults_to_unknown(assessor):
    assert assessor.calculate_threat("PERIMETER", "Person") == assessor.calculate_threat(
        "PERIMETER", "Person", face_status="UNKNOWN"
    )


def test_verifying_face_adds_zero_with_reason(assessor):
    # WARNING 30 + Person 30 + 0 = 60 WARNING
    score, category, reasons = assessor.calculate_threat("WARNING", "Person", face_status="VERIFYING")
    assert score == 60
    assert category == "WARNING"
    assert reasons == ["In Warning Zone", "Verifying liveness"]


def test_na_face_adds_nothing_and_no_reason(assessor):
    # WARNING 30 + Person 30 = 60 WARNING, no identity reason at all
    score, category, reasons = assessor.calculate_threat("WARNING", "Person", face_status="N/A")
    assert score == 60
    assert category == "WARNING"
    assert reasons == ["In Warning Zone"]


def test_unrecognised_face_status_is_treated_as_unknown(assessor):
    # v1 behaviour: anything that is not KNOWN/SPOOF (now also VERIFYING/N/A) is unknown.
    assert assessor.calculate_threat("SAFE", "Person", face_status="garbage") == (
        50,
        "WARNING",
        ["In Safe Zone", "Unknown Identity"],
    )


# --------------------------------------------------------------------------- #
# behaviour rules
# --------------------------------------------------------------------------- #
def test_crawling_adds_50(assessor):
    # SAFE 0 + Dog 10 + crawl 50 = 60 WARNING
    score, category, reasons = assessor.calculate_threat("SAFE", "Dog", is_crawling=True)
    assert score == 60
    assert category == "WARNING"
    assert reasons == ["In Safe Zone", "Animal Detected", "Suspicious Posture: Crawling/Prone"]


def test_anomaly_adds_40_with_type_in_reason(assessor):
    # SAFE 0 + Dog 10 + anomaly 40 = 50 WARNING
    score, category, reasons = assessor.calculate_threat("SAFE", "Dog", is_anomaly=True, anomaly_type="running")
    assert score == 50
    assert category == "WARNING"
    assert reasons == ["In Safe Zone", "Animal Detected", "Anomalous Behavior: running"]
    assert "running" in reasons[-1]


def test_anomaly_without_type_uses_generic_reason(assessor):
    score, _, reasons = assessor.calculate_threat("SAFE", "Dog", is_anomaly=True)
    assert score == 50
    assert reasons[-1] == "Anomalous/Suspicious Behavior"


def test_anomaly_type_is_ignored_when_not_anomalous(assessor):
    score, _, reasons = assessor.calculate_threat("SAFE", "Dog", is_anomaly=False, anomaly_type="running")
    assert score == 10
    assert reasons == ["In Safe Zone", "Animal Detected"]


def test_crawling_and_anomaly_stack(assessor):
    # SAFE 0 + Dog 10 + 50 + 40 = 100 (exactly at the cap)
    score, category, reasons = assessor.calculate_threat(
        "SAFE", "Dog", is_crawling=True, is_anomaly=True, anomaly_type="erratic"
    )
    assert score == 100
    assert category == "CRITICAL"
    assert reasons == [
        "In Safe Zone",
        "Animal Detected",
        "Suspicious Posture: Crawling/Prone",
        "Anomalous Behavior: erratic",
    ]


# --------------------------------------------------------------------------- #
# loitering rule
# --------------------------------------------------------------------------- #
def test_loitering_adds_20_at_threshold(assessor):
    # PERIMETER 20 + Dog 10 + loiter 20 = 50
    score, category, reasons = assessor.calculate_threat("PERIMETER", "Dog", loiter_seconds=10.0)
    assert score == 50
    assert category == "WARNING"
    assert reasons == ["In Perimeter", "Animal Detected", "Loitering 10s"]


def test_loitering_below_threshold_adds_nothing(assessor):
    score, _, reasons = assessor.calculate_threat("PERIMETER", "Dog", loiter_seconds=9.99)
    assert score == 30
    assert reasons == ["In Perimeter", "Animal Detected"]


def test_loitering_reason_uses_whole_seconds(assessor):
    _, _, reasons = assessor.calculate_threat("PERIMETER", "Dog", loiter_seconds=12.7)
    assert reasons[-1] == "Loitering 12s"


def test_loitering_not_applied_in_safe_zone(assessor):
    score, _, reasons = assessor.calculate_threat("SAFE", "Dog", loiter_seconds=999)
    assert score == 10
    assert reasons == ["In Safe Zone", "Animal Detected"]


def test_loitering_not_applied_for_known_face(assessor):
    # CRITICAL 40 + Person 30 - 50 = 20, no loitering bump for a resident
    score, _, reasons = assessor.calculate_threat("CRITICAL", "Person", face_status="KNOWN", loiter_seconds=60)
    assert score == 20
    assert reasons == ["Breached Critical Zone", "Authorized Personnel"]


@pytest.mark.parametrize("status", ["UNKNOWN", "SPOOF", "VERIFYING", "N/A"])
def test_loitering_applies_to_every_non_known_face(assessor, status):
    _, _, reasons = assessor.calculate_threat("PERIMETER", "Person", face_status=status, loiter_seconds=10)
    assert reasons[-1] == "Loitering 10s"


def test_loitering_uses_per_call_threshold_override(assessor):
    # assessor threshold is 10; per-call 3 makes 5s count, per-call 30 makes it not count
    score_low, _, reasons_low = assessor.calculate_threat("PERIMETER", "Dog", loiter_seconds=5, loiter_threshold=3)
    assert score_low == 50 and reasons_low[-1] == "Loitering 5s"
    score_high, _, reasons_high = assessor.calculate_threat("PERIMETER", "Dog", loiter_seconds=5, loiter_threshold=30)
    assert score_high == 30 and reasons_high == ["In Perimeter", "Animal Detected"]


def test_loitering_threshold_none_falls_back_to_settings_default():
    # settings.LOITER_SECONDS is 10.0: 10s loiters, 9s does not.
    default = ThreatAssessor()
    assert default.calculate_threat("PERIMETER", "Dog", loiter_seconds=10, loiter_threshold=None)[0] == 50
    assert default.calculate_threat("PERIMETER", "Dog", loiter_seconds=9, loiter_threshold=None)[0] == 30


def test_loitering_threshold_zero_disables_rule(assessor):
    # Contract is silent on <= 0; chosen reading: rule disabled (otherwise every
    # track would "loiter 0s" from its first frame).
    score, _, reasons = assessor.calculate_threat("PERIMETER", "Dog", loiter_seconds=0, loiter_threshold=0)
    assert score == 30
    assert reasons == ["In Perimeter", "Animal Detected"]
    assert ThreatAssessor(loiter_threshold=0).calculate_threat("PERIMETER", "Dog", loiter_seconds=500)[0] == 30


# --------------------------------------------------------------------------- #
# weapon short-circuit
# --------------------------------------------------------------------------- #
def test_weapon_short_circuits_to_100_critical(assessor):
    assert assessor.calculate_threat("SAFE", "Person", has_weapon=True) == (100, "CRITICAL", [WEAPON_REASON])


def test_weapon_overrides_known_face_and_safe_zone(assessor):
    # Without the weapon this would be 30 - 50 => 0 LOW.
    assert assessor.calculate_threat("SAFE", "Person", face_status="KNOWN") == (
        0,
        "LOW",
        ["In Safe Zone", "Authorized Personnel"],
    )
    assert assessor.calculate_threat("SAFE", "Person", face_status="KNOWN", has_weapon=True) == (
        100,
        "CRITICAL",
        [WEAPON_REASON],
    )


def test_weapon_reason_is_the_only_reason(assessor):
    _, _, reasons = assessor.calculate_threat(
        "CRITICAL",
        "Person",
        face_status="SPOOF",
        is_anomaly=True,
        anomaly_type="running",
        is_crawling=True,
        has_weapon=True,
        loiter_seconds=100,
    )
    assert reasons == [WEAPON_REASON]


def test_weapon_with_unknown_object_and_zone(assessor):
    assert assessor.calculate_threat("MOON", "Unknown", has_weapon=True) == (100, "CRITICAL", [WEAPON_REASON])


# --------------------------------------------------------------------------- #
# clamping
# --------------------------------------------------------------------------- #
def test_score_clamps_at_100(assessor):
    # 40 + 30 + 50 + 50 + 40 + 20 = 230 -> 100
    score, category, reasons = assessor.calculate_threat(
        "CRITICAL",
        "Person",
        face_status="SPOOF",
        is_crawling=True,
        is_anomaly=True,
        anomaly_type="running",
        loiter_seconds=30,
    )
    assert score == 100
    assert category == "CRITICAL"
    assert reasons == [
        "Breached Critical Zone",
        "Spoofing Attempt Detected",
        "Suspicious Posture: Crawling/Prone",
        "Anomalous Behavior: running",
        "Loitering 30s",
    ]


def test_score_clamps_at_0(assessor):
    # 0 + 30 - 50 = -20 -> 0
    score, category, reasons = assessor.calculate_threat("SAFE", "Person", face_status="KNOWN")
    assert score == 0
    assert category == "LOW"
    assert reasons == ["In Safe Zone", "Authorized Personnel"]


def test_known_person_in_perimeter_is_exactly_zero(assessor):
    # 20 + 30 - 50 = 0, no clamp needed but still LOW
    assert assessor.calculate_threat("PERIMETER", "Person", face_status="KNOWN")[0] == 0


def test_score_is_int_and_within_range(assessor):
    score, category, reasons = assessor.calculate_threat("WARNING", "Person", loiter_seconds=15.5)
    assert isinstance(score, int)
    assert 0 <= score <= 100
    assert isinstance(category, str)
    assert isinstance(reasons, list) and all(isinstance(r, str) for r in reasons)


# --------------------------------------------------------------------------- #
# category boundaries
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "score, expected",
    [(0, "LOW"), (29, "LOW"), (30, "WARNING"), (69, "WARNING"), (70, "CRITICAL"), (100, "CRITICAL")],
)
def test_categorize_boundaries(score, expected):
    assert categorize(score) == expected


def test_category_boundaries_reached_through_calculate_threat(assessor):
    # 29 is not reachable from the weights, so exercise the nearest real scores.
    assert assessor.calculate_threat("PERIMETER", "Dog") == (30, "WARNING", ["In Perimeter", "Animal Detected"])
    assert assessor.calculate_threat("CRITICAL", "Person", face_status="KNOWN")[0:2] == (20, "LOW")
    assert assessor.calculate_threat("WARNING", "Person", face_status="N/A")[0:2] == (60, "WARNING")
    assert assessor.calculate_threat("CRITICAL", "Person", face_status="N/A")[0:2] == (70, "CRITICAL")
    assert assessor.calculate_threat("PERIMETER", "Person", face_status="UNKNOWN")[0:2] == (70, "CRITICAL")


# --------------------------------------------------------------------------- #
# reasons list contents / ordering
# --------------------------------------------------------------------------- #
def test_reasons_follow_rule_order(assessor):
    _, _, reasons = assessor.calculate_threat(
        "WARNING",
        "Person",
        face_status="UNKNOWN",
        is_crawling=True,
        is_anomaly=True,
        anomaly_type="fall",
        loiter_seconds=11,
    )
    assert reasons == [
        "In Warning Zone",
        "Unknown Identity",
        "Suspicious Posture: Crawling/Prone",
        "Anomalous Behavior: fall",
        "Loitering 11s",
    ]


def test_reasons_are_a_fresh_list_each_call(assessor):
    _, _, first = assessor.calculate_threat("SAFE", "Dog")
    first.append("mutated by caller")
    _, _, second = assessor.calculate_threat("SAFE", "Dog")
    assert second == ["In Safe Zone", "Animal Detected"]
    assert first is not second


# --------------------------------------------------------------------------- #
# purity
# --------------------------------------------------------------------------- #
def test_function_is_pure_same_inputs_same_outputs(assessor):
    kwargs = dict(
        zone_level="WARNING",
        object_type="Person",
        face_status="SPOOF",
        is_anomaly=True,
        is_crawling=False,
        has_weapon=False,
        loiter_seconds=42.0,
        anomaly_type="running",
    )
    first = assessor.calculate_threat(**kwargs)
    snapshot = copy.deepcopy(vars(assessor))
    for _ in range(50):
        assert assessor.calculate_threat(**kwargs) == first
    assert vars(assessor) == snapshot  # no state accumulated between calls


def test_calls_do_not_influence_each_other(assessor):
    high = assessor.calculate_threat("CRITICAL", "Person", face_status="SPOOF", has_weapon=False)
    low = assessor.calculate_threat("SAFE", "Person", face_status="KNOWN")
    assert assessor.calculate_threat("CRITICAL", "Person", face_status="SPOOF", has_weapon=False) == high
    assert assessor.calculate_threat("SAFE", "Person", face_status="KNOWN") == low
    assert high == (100, "CRITICAL", ["Breached Critical Zone", "Spoofing Attempt Detected"])
    assert low == (0, "LOW", ["In Safe Zone", "Authorized Personnel"])


def test_two_assessors_with_same_config_agree():
    a, b = ThreatAssessor(10), ThreatAssessor(10)
    args = ("PERIMETER", "Person", "VERIFYING", True, True, False, 20.0, "erratic")
    assert (
        a.calculate_threat(*args)
        == b.calculate_threat(*args)
        == (
            100,
            "CRITICAL",
            [
                "In Perimeter",
                "Verifying liveness",
                "Suspicious Posture: Crawling/Prone",
                "Anomalous Behavior: erratic",
                "Loitering 20s",
            ],
        )
    )
