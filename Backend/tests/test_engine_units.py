"""Camera, detectors, posture and predictor with fakes (no real camera, no models)."""

import time

import numpy as np
import pytest

from src.engine.camera import ThreadedCamera, source_label
from src.engine.detectors import Detection, PoseEstimator, PosePerson, YoloTracker
from src.engine.posture import match_pose_to_bbox, posture_from_keypoints
from src.predictor import MovementPredictor


# ------------------------------------------------------------------ camera
class FakeCapture:
    """A cv2.VideoCapture stand-in that yields `n` frames then fails (or blocks)."""

    def __init__(self, n=5, opened=True, fps=30.0, delay=0.0):
        self.n, self._opened, self.fps, self.delay = n, opened, fps, delay
        self.i = 0
        self.released = False
        self.seeks = 0

    def isOpened(self):
        return self._opened

    def read(self):
        if self.delay:
            time.sleep(self.delay)
        if self.i >= self.n:
            return False, None
        self.i += 1
        frame = np.full((4, 6, 3), self.i, np.uint8)
        return True, frame

    def get(self, prop):
        return self.fps

    def set(self, prop, value):
        self.seeks += 1
        self.i = 0
        return True

    def release(self):
        self.released = True


@pytest.mark.parametrize(
    "source,label",
    [
        (0, "camera:0"),
        (
            "rtsp://user:p%40ss@10.0.0.5:554/Streaming/Channels/101?token=abc&x=1",
            "rtsp://10.0.0.5:554/Streaming/Channels/101",
        ),
        ("http://cam.local/stream.mjpg?key=s3cret", "http://cam.local/stream.mjpg"),
        ("/Users/me/private videos/clip.mp4", "clip.mp4"),
    ],
)
def test_source_label_strips_credentials_query_and_paths(source, label):
    assert source_label(source) == label
    assert "user" not in label and "token" not in label and "private" not in label


def test_camera_reads_new_frames_blocks_and_copies(tmp_path):
    cap = FakeCapture(n=3, delay=0.01)
    cam = ThreadedCamera("fake", capture_factory=lambda s: cap, reconnect_delay=0.05, stall_seconds=5)
    cam.start()
    ok, frame, seq = cam.read(last_seq=0, timeout=1.0)
    assert ok and frame is not None and seq >= 1
    ok2, frame2, seq2 = cam.read(last_seq=seq, timeout=1.0)
    assert ok2 and seq2 > seq
    frame2[:] = 0  # our copy; the camera's buffer is untouched
    _, again, _ = cam.read()
    assert again is not None and again.max() > 0
    cam.stop()
    assert cap.released


def test_camera_reconnects_after_failure_and_marks_offline():
    caps = [FakeCapture(n=1), FakeCapture(n=0, opened=False), FakeCapture(n=50, delay=0.005)]
    made = []

    def factory(source):
        c = caps[min(len(made), len(caps) - 1)]
        made.append(c)
        return c

    cam = ThreadedCamera("fake", capture_factory=factory, reconnect_delay=0.05, stall_seconds=0.2)
    cam.start()
    deadline = time.time() + 3
    while len(made) < 3 and time.time() < deadline:
        time.sleep(0.02)
    assert len(made) >= 3 and caps[0].released
    ok, _, seq = cam.read(last_seq=1, timeout=1.0)
    assert ok and cam.online
    cam.stop()
    time.sleep(0.3)
    assert not cam.online  # stall watchdog: no frames since stop


def test_file_source_loops_instead_of_going_offline(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")  # only needs to exist for isfile()
    cap = FakeCapture(n=2, fps=200.0)
    cam = ThreadedCamera(str(clip), capture_factory=lambda s: cap, stall_seconds=5)
    cam.start()
    deadline = time.time() + 2
    while cap.seeks < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert cap.seeks >= 2 and cam.online and not cap.released
    cam.stop()


def test_stop_is_bounded_when_capture_blocks():
    cap = FakeCapture(n=100, delay=0.3)
    cam = ThreadedCamera("fake", capture_factory=lambda s: cap)
    cam.start()
    t0 = time.time()
    cam.stop()
    assert time.time() - t0 < 3.0


# ------------------------------------------------------------------ detectors
class FakeBoxes:
    def __init__(self, rows, with_ids=True):
        self.xyxy = np.array([r[0] for r in rows], dtype=float).reshape(-1, 4)
        self.cls = np.array([r[1] for r in rows], dtype=float)
        self.conf = np.array([r[2] for r in rows], dtype=float)
        self.id = np.array([r[3] for r in rows], dtype=float) if with_ids and rows else None

    def __len__(self):
        return len(self.cls)


class FakeResult:
    def __init__(self, boxes, keypoints=None):
        self.boxes, self.keypoints = boxes, keypoints


class FakeModel:
    def __init__(self, path):
        self.path = path
        self.calls = []
        self.rows = []
        self.with_ids = True

    def track(self, frame, **kw):
        self.calls.append(kw)
        return [FakeResult(FakeBoxes(self.rows, self.with_ids))]

    def predict(self, frame, **kw):
        self.calls.append(kw)
        return [FakeResult(FakeBoxes(self.rows), self.kp)]


def test_tracker_passes_kwargs_filters_floors_and_handles_missing_ids():
    made = []

    def factory(path):
        m = FakeModel(path)
        made.append(m)
        return m

    t = YoloTracker("m.pt", {0: "Person", 43: "Knife"}, 0.65, {43: 0.35}, model_factory=factory)
    assert made == []  # lazy
    t.warmup()
    m = made[0]
    kw = m.calls[0]
    assert kw["persist"] and kw["tracker"] == "bytetrack.yaml" and kw["device"] == "cpu"
    assert kw["classes"] == [0, 43] and kw["conf"] == 0.35
    m.rows = [
        ((0, 0, 10, 20), 0, 0.9, 1),
        ((5, 5, 8, 9), 43, 0.4, 2),
        ((0, 0, 3, 3), 0, 0.5, 3),
        ((1, 1, 2, 2), 7, 0.99, 4),
    ]
    dets = t.track(np.zeros((480, 640, 3), np.uint8))
    assert dets == [Detection(1, 0, 0.9, (0, 0, 10, 20)), Detection(2, 43, 0.4, (5, 5, 8, 9))]
    m.with_ids = False
    assert t.track(np.zeros((480, 640, 3), np.uint8)) == []  # first-appearance frame


def test_pose_estimator_returns_keypoints_with_conf_and_draws():
    m = FakeModel("p.pt")
    m.rows = [((0, 0, 10, 20), 0, 0.9, 1)]

    class KP:
        xy = np.ones((1, 17, 2)) * 5
        conf = np.ones((1, 17)) * 0.8

    m.kp = KP()
    p = PoseEstimator("p.pt", model_factory=lambda path: m)
    people = p.estimate(np.zeros((480, 640, 3), np.uint8))
    assert len(people) == 1 and people[0].keypoints.shape == (17, 3) and people[0].bbox == (0, 0, 10, 20)
    assert m.calls[-1]["device"] == "cpu"
    frame = np.zeros((480, 640, 3), np.uint8)
    p.draw(frame, people)
    assert frame.max() > 0


# ------------------------------------------------------------------ posture
def kpts(shoulders, hips, conf=0.9):
    k = np.zeros((17, 3))
    k[5, :2], k[6, :2] = shoulders
    k[11, :2], k[12, :2] = hips
    k[[5, 6, 11, 12], 2] = conf
    return k


def test_posture_upright_prone_bending_and_unknown():
    upright = kpts([(90, 100), (110, 100)], [(92, 200), (108, 200)])
    assert posture_from_keypoints(upright, (80, 80, 120, 300)) == "UPRIGHT"
    prone = kpts([(100, 150), (100, 170)], [(220, 155), (220, 165)])
    assert posture_from_keypoints(prone, (80, 140, 240, 180)) == "PRONE"  # wide box
    assert posture_from_keypoints(prone, (80, 100, 240, 400)) == "UPRIGHT"  # bending: tall box
    assert posture_from_keypoints(prone) == "PRONE"  # angle-only when no bbox
    low = kpts([(90, 100), (110, 100)], [(92, 200), (108, 200)], conf=0.2)
    assert posture_from_keypoints(low, (80, 80, 120, 300)) == "UNKNOWN"
    end_on = kpts([(100, 100), (102, 100)], [(100, 104), (102, 104)])
    assert posture_from_keypoints(end_on, (80, 80, 120, 300)) == "UNKNOWN"
    assert posture_from_keypoints(np.zeros((5, 3))) == "UNKNOWN"


def test_match_pose_to_bbox_by_iou():
    a = PosePerson((0, 0, 100, 100), np.zeros((17, 3)))
    b = PosePerson((90, 90, 200, 200), np.zeros((17, 3)))
    assert match_pose_to_bbox((5, 5, 105, 105), [a, b]) is a
    assert match_pose_to_bbox((500, 500, 600, 600), [a, b]) is None
    assert match_pose_to_bbox((50, 50, 150, 150), [a, b], min_iou=0.5) is None


# ------------------------------------------------------------------ predictor
def test_predictor_direction_prediction_and_prune():
    p = MovementPredictor()
    for i in range(6):
        p.update(1, 10 * i, 0)
    assert p.get_direction(1) == "East ->"
    assert p.predict_next_position(1, frames_ahead=1) == (60, 0)
    p.update(2, 0, 0)
    p.prune([1])
    assert 2 not in p.history and p.get_direction(9) == "Analyzing"
