from src.liveness_detector import BlinkTracker, LivenessDetector, ear_from_landmarks, eye_aspect_ratio

OPEN, CLOSED, BORDER = 0.32, 0.12, 0.23
FPS = 15.0


def feed(tracker, samples, start=0.0, fps=FPS):
    """Feed a list of EAR samples at a fixed frame rate; return (any_blink, last_t)."""
    t = start
    blinked = False
    for ear in samples:
        blinked |= tracker.update(ear, t)
        t += 1.0 / fps
    return blinked, t


def test_ear_geometry():
    square_eye = [(0, 0), (1, 1), (2, 1), (3, 0), (2, -1), (1, -1)]
    assert abs(eye_aspect_ratio(square_eye) - (2 + 2) / (2 * 3)) < 1e-9
    assert eye_aspect_ratio([(0, 0)] * 3) == 0.0
    assert ear_from_landmarks(None) is None
    assert ear_from_landmarks({"left_eye": square_eye}) is None
    assert ear_from_landmarks({"left_eye": square_eye, "right_eye": square_eye}) == eye_aspect_ratio(square_eye)


def test_real_blink_is_credited_and_expires():
    b = BlinkTracker(ear_thresh=0.22, ttl=5.0)
    blinked, t = feed(b, [OPEN] * 5 + [CLOSED] * 3 + [OPEN])
    assert blinked and b.blinks == 1
    assert b.is_live(t) and not b.is_live(t + 6.0)
    assert b.observed_s == 0.0  # reset by the blink; later samples accumulate again


def test_long_closure_is_not_a_blink():
    b = BlinkTracker(ear_thresh=0.22, max_blink_s=0.8)
    blinked, _ = feed(b, [OPEN] * 5 + [CLOSED] * 30 + [OPEN] * 2)  # 2 s closed
    assert not blinked and b.blinks == 0


def test_closure_without_open_preamble_is_ignored():
    b = BlinkTracker(ear_thresh=0.22)
    # borderline-open samples never satisfy the +0.03 margin, so no valid preamble
    blinked, _ = feed(b, [BORDER] * 5 + [CLOSED] * 3 + [OPEN] * 2)
    assert not blinked
    blinked, _ = feed(b, [CLOSED] * 3 + [OPEN] * 2, start=10.0)
    assert not blinked


def test_observed_accumulates_and_resets_on_gap():
    b = BlinkTracker(ear_thresh=0.22, gap_reset_s=1.0)
    feed(b, [OPEN] * 16)  # 15 intervals of 1/15 s
    assert abs(b.observed_s - 1.0) < 1e-6
    b.update(OPEN, 10.0)  # 9 s gap -> continuous window restarts
    assert b.observed_s == 0.0
    b.update(OPEN, 10.9)  # a large single step is capped at 0.5 s
    assert b.observed_s == 0.5
    b.update(None, 11.0)  # invalid samples add nothing
    assert b.observed_s == 0.5


def test_two_blinks_counted_separately():
    b = BlinkTracker(ear_thresh=0.22)
    pattern = [OPEN] * 5 + [CLOSED] * 2 + [OPEN] * 5 + [CLOSED] * 2 + [OPEN] * 2
    feed(b, pattern)
    assert b.blinks == 2


def test_detector_factory_uses_thresholds():
    tracker = LivenessDetector(ear_thresh=0.3, ttl=7.0).new_tracker()
    assert tracker.ear_thresh == 0.3 and tracker.ttl == 7.0
