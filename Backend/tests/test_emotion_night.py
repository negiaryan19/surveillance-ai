"""EmotionDetector (landmark heuristics, no dlib) and NightVision (real cv2 on synthetic frames)."""

import sys
import threading

import numpy as np
import pytest

from src.emotion_detector import EmotionDetector
from src.night_vision import NightVision


# ------------------------------------------------------------------ landmark fixtures
def eye(cx, cy, w=20, h=8):
    """Six dlib eye points around a centre; height controls the aspect ratio."""
    return [
        (cx - w, cy),
        (cx - w / 2, cy - h / 2),
        (cx + w / 2, cy - h / 2),
        (cx + w, cy),
        (cx + w / 2, cy + h / 2),
        (cx - w / 2, cy + h / 2),
    ]


def landmarks(*, eye_h=8, mouth_gap=4, mouth_w=40, face_w=120, brow_lift=25):
    """A schematic face: chin arc, two eyes, brows and a 12-point lip pair."""
    cx, cy = 100, 100
    chin = [(cx - face_w / 2 + i * face_w / 16, cy + 60 + (0 if i in (0, 16) else 10)) for i in range(17)]
    left_eye, right_eye = eye(cx - 30, cy - 10, h=eye_h), eye(cx + 30, cy - 10, h=eye_h)
    left_brow = [(x, y - brow_lift) for x, y in left_eye[:5]]
    right_brow = [(x, y - brow_lift) for x, y in right_eye[:5]]
    top = [(cx - mouth_w / 2 + i * mouth_w / 6, cy + 30) for i in range(7)] + [
        (cx + mouth_w / 4 - i * mouth_w / 8, cy + 30 + 1) for i in range(5)
    ]
    bottom = [(cx + mouth_w / 2 - i * mouth_w / 6, cy + 30 + mouth_gap) for i in range(7)] + [
        (cx - mouth_w / 4 + i * mouth_w / 8, cy + 30 + mouth_gap - 1) for i in range(5)
    ]
    return {
        "chin": chin,
        "left_eye": left_eye,
        "right_eye": right_eye,
        "left_eyebrow": left_brow,
        "right_eyebrow": right_brow,
        "top_lip": top,
        "bottom_lip": bottom,
    }


@pytest.fixture
def det():
    return EmotionDetector()


def test_classify_returns_shape_and_signals(det):
    out = det.classify(landmarks())
    assert set(out) == {"emotion", "confidence", "signals"}
    assert out["emotion"] in {"Neutral", "Focused", "Happy", "Surprised", "Tired", "Unknown"}
    assert set(out["signals"]) == {"eye_ratio", "mouth_open", "mouth_width", "brow_gap"}
    assert 50 <= out["confidence"] <= 95


def test_classify_without_landmarks_is_unknown(det):
    assert det.classify(None) == {"emotion": "Unknown", "confidence": 0, "signals": {}}
    assert det.classify({}) == {"emotion": "Unknown", "confidence": 0, "signals": {}}
    partial = det.classify({"left_eye": eye(0, 0)})  # missing everything else
    assert partial["emotion"] in {"Neutral", "Unknown", "Focused"}


def test_tired_when_eyes_nearly_closed(det):
    out = det.classify(landmarks(eye_h=2))
    assert out["emotion"] == "Tired" and out["confidence"] > 50


def test_surprised_when_mouth_wide_open_and_eyes_open(det):
    out = det.classify(landmarks(eye_h=12, mouth_gap=30, mouth_w=40))
    assert out["emotion"] == "Surprised"


def test_happy_when_mouth_wide_relative_to_face(det):
    # mouth_width = 70/120 = 0.58 > 0.44 and mouth_open = 10/70 = 0.14 > 0.11
    out = det.classify(landmarks(eye_h=10, mouth_gap=10, mouth_w=70, face_w=120))
    assert out["emotion"] == "Happy"


def test_confidence_grows_with_margin(det):
    # EAR = eye_h / 40 with this eye geometry: 7 -> 0.175 (just under the 0.18 Tired threshold), 1 -> 0.025
    weak = det.classify(landmarks(eye_h=7))["confidence"]
    strong = det.classify(landmarks(eye_h=1))["confidence"]
    assert weak < 60 < strong <= 95


def test_confidence_clamped():
    assert EmotionDetector._confidence(-5) == 50
    assert EmotionDetector._confidence(0.5) == 72
    assert EmotionDetector._confidence(99) == 95


def test_detect_wrapper_uses_dlib_under_the_lock(monkeypatch, det):
    """detect() must call face_landmarks while holding DLIB_LOCK (dlib is not re-entrant)."""
    from src import face_recognizer as fr

    seen = {}

    class FakeDlib:
        @staticmethod
        def face_landmarks(rgb):
            seen["locked"] = not fr.DLIB_LOCK.acquire(blocking=False) or (fr.DLIB_LOCK.release() or False)
            seen["shape"] = rgb.shape
            return [landmarks()]

    # RLock: the same thread can re-acquire, so probe from another thread instead.
    def probe():
        seen["other_thread_blocked"] = not fr.DLIB_LOCK.acquire(blocking=False)
        if not seen["other_thread_blocked"]:
            fr.DLIB_LOCK.release()

    class ProbingDlib(FakeDlib):
        @staticmethod
        def face_landmarks(rgb):
            t = threading.Thread(target=probe)
            t.start()
            t.join()
            seen["shape"] = rgb.shape
            return [landmarks()]

    monkeypatch.setitem(sys.modules, "face_recognition", ProbingDlib)
    frame = np.zeros((200, 300, 3), np.uint8)
    out = det.detect(frame, (50, 50, 150, 150))
    assert out["emotion"] != "Unknown"
    assert seen["other_thread_blocked"] is True  # the lock was held during the dlib call
    assert seen["shape"][2] == 3 and seen["shape"][0] > 100  # padded crop, RGB


def test_detect_survives_missing_library(monkeypatch, det):
    monkeypatch.setitem(sys.modules, "face_recognition", None)
    assert det.detect(np.zeros((50, 50, 3), np.uint8), (0, 0, 40, 40))["emotion"] == "Unknown"


# ------------------------------------------------------------------ night vision
def test_low_light_threshold_and_enhance_keeps_shape():
    nv = NightVision(threshold=70)
    dark = np.full((48, 64, 3), 30, np.uint8)
    bright = np.full((48, 64, 3), 160, np.uint8)
    assert nv.is_low_light(dark) and not nv.is_low_light(bright)
    out = nv.enhance(dark)
    assert out.shape == dark.shape and out.dtype == np.uint8


def test_enhance_raises_contrast_of_a_dim_scene():
    nv = NightVision()
    rng = np.random.default_rng(1)
    dim = (rng.normal(40, 6, size=(120, 160, 3)).clip(0, 255)).astype(np.uint8)
    out = nv.enhance(dim)
    assert out.std() > dim.std()  # CLAHE spreads the histogram


def test_default_threshold_is_not_triggered_by_ordinary_indoor_frames():
    nv = NightVision()
    indoor = np.full((48, 64, 3), 80, np.uint8)
    assert not nv.is_low_light(indoor)
