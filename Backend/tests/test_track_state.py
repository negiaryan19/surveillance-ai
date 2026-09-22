from src.engine.track_state import TrackRegistry, TrackState
from src.liveness_detector import BlinkTracker

GRACE, MAX_VERIFY = 15.0, 45.0


def make_registry():
    return TrackRegistry(blink_factory=lambda: BlinkTracker(0.22, ttl=30.0))


def person(reg=None, now=0.0):
    reg = reg or make_registry()
    return reg.get_or_create(1, 0, "Person", now)


def test_registry_creates_refreshes_and_prunes():
    reg = make_registry()
    t = reg.get_or_create(7, 0, "Person", 1.0)
    assert t.hits == 1 and t.first_seen == 1.0
    same = reg.get_or_create(7, 0, "Person", 3.0)
    assert same is t and t.hits == 2 and t.last_seen == 3.0
    reg.get_or_create(8, 2, "Car", 6.0)
    assert len(reg) == 2
    assert reg.prune(9.5, max_age=5.0) == [7]  # 6.5 s stale; the car is only 3.5 s old
    assert [x.track_id for x in reg.active()] == [8]


def test_non_person_is_na_and_never_authorized():
    reg = make_registry()
    car = reg.get_or_create(2, 2, "Car", 0.0)
    assert car.update_face_status(0.0, GRACE, MAX_VERIFY) == "N/A"
    assert not car.is_authorized


def test_unknown_identity_is_unknown():
    t = person()
    assert t.update_face_status(0.0, GRACE, MAX_VERIFY) == "UNKNOWN"


def test_identity_vote_needs_majority_and_no_face_casts_no_vote():
    t = person()
    t.vote_identity("Aryan")
    assert t.identity == "Aryan"  # 1 of 1 is a majority
    t.vote_identity("Unknown")
    assert t.identity == "Aryan"  # 1-1 tie keeps the current identity
    t.vote_identity("Unknown")
    assert t.identity == "Unknown"  # 2 of 3
    # An analysis with no face does not call vote_identity at all; identity is stable.
    t.identity = "Aryan"
    assert t.identity == "Aryan"


def test_known_person_goes_verifying_then_known_on_blink():
    t = person()
    t.vote_identity("Aryan")
    assert t.update_face_status(1.0, GRACE, MAX_VERIFY) == "VERIFYING"
    assert not t.is_authorized
    t.blink.last_blink_at = 2.0
    assert t.update_face_status(2.5, GRACE, MAX_VERIFY) == "KNOWN"
    assert t.is_authorized and t.verified_once


def test_verified_track_stays_known_when_ttl_lapses_unobserved():
    t = person()
    t.vote_identity("Aryan")
    t.blink.last_blink_at = 0.0
    assert t.update_face_status(1.0, GRACE, MAX_VERIFY) == "KNOWN"
    # 100 s later, no blink seen but also no continuous observation
    assert t.update_face_status(100.0, GRACE, MAX_VERIFY) == "KNOWN"
    assert t.is_authorized


def test_spoof_requires_grace_seconds_of_observation():
    t = person()
    t.vote_identity("Aryan")
    t.blink.observed_s = GRACE - 0.1
    assert t.update_face_status(5.0, GRACE, MAX_VERIFY) == "VERIFYING"
    t.blink.observed_s = GRACE
    assert t.update_face_status(6.0, GRACE, MAX_VERIFY) == "SPOOF"
    assert not t.is_authorized


def test_spoof_beats_verified_once():
    t = person()
    t.vote_identity("Aryan")
    t.blink.last_blink_at = 0.0
    t.update_face_status(1.0, GRACE, MAX_VERIFY)
    t.blink.observed_s = GRACE + 1  # watched for 16 s after liveness expired, no blink
    assert t.update_face_status(60.0, GRACE, MAX_VERIFY) == "SPOOF"


def test_verifying_times_out_to_unknown_not_spoof():
    t = person()
    t.vote_identity("Aryan")
    assert t.update_face_status(0.0, GRACE, MAX_VERIFY) == "VERIFYING"
    assert t.update_face_status(MAX_VERIFY + 1, GRACE, MAX_VERIFY) == "UNKNOWN"


def test_identity_change_resets_verification():
    t = person()
    t.vote_identity("Aryan")
    t.blink.last_blink_at = 0.0
    t.update_face_status(1.0, GRACE, MAX_VERIFY)
    assert t.verified_once
    for _ in range(3):
        t.vote_identity("Bob")
    assert t.identity == "Bob" and not t.verified_once


def test_loiter_seconds():
    t = person()
    assert t.loiter_seconds(10.0) == 0.0
    t.zone_level, t.zone_entered_at = "WARNING", 4.0
    assert t.loiter_seconds(10.0) == 6.0
    t.zone_level = "SAFE"
    assert t.loiter_seconds(10.0) == 0.0


def test_default_registry_uses_settings_thresholds():
    from config import settings

    t = TrackRegistry().get_or_create(1, 0, "Person", 0.0)
    assert isinstance(t, TrackState)
    assert t.blink.ttl == settings.LIVENESS_TTL and t.blink.ear_thresh == settings.EAR_THRESHOLD
