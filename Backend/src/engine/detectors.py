"""YOLO object tracking and pose estimation, one instance per camera thread.

ByteTrack state lives inside the YOLO predictor, so cameras must not share a
tracker. Its track-id counter is process-global and reset whenever a tracker
is constructed, which is why :meth:`YoloTracker.warmup` exists: the engine
warms every camera up sequentially BEFORE any worker thread starts, and a
tracker is never re-created afterwards.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import NamedTuple

import cv2
import numpy as np

log = logging.getLogger("chanakya.detectors")

DEVICE = "cpu"  # MPS is not safe from worker threads; CPU does ~18 FPS/camera here

# COCO keypoint skeleton (index pairs) for drawing.
_SKELETON = (
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 6),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (0, 1),
    (0, 2),
    (1, 3),
    (2, 4),
)


class Detection(NamedTuple):
    track_id: int
    class_id: int
    conf: float
    bbox: tuple[int, int, int, int]


class PosePerson(NamedTuple):
    bbox: tuple[int, int, int, int]
    keypoints: np.ndarray  # (17, 3): x, y, conf


def _load_yolo(model_path: str):
    from ultralytics import YOLO

    return YOLO(model_path)


class YoloTracker:
    def __init__(
        self,
        model_path: str,
        classes: dict,
        conf_floor: float,
        class_conf: dict | None = None,
        model_factory: Callable[[str], object] | None = None,
    ) -> None:
        self.model_path = model_path
        self.classes = {int(k): v for k, v in classes.items()}
        self.conf_floor = float(conf_floor)
        self.class_conf = {int(k): float(v) for k, v in (class_conf or {}).items()}
        self._factory = model_factory or _load_yolo
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            self._model = self._factory(self.model_path)
        return self._model

    def warmup(self) -> None:
        self.track(np.zeros((480, 640, 3), dtype=np.uint8))

    def track(self, frame) -> list[Detection]:
        model = self._ensure_model()
        floors = [self.conf_floor] + list(self.class_conf.values())
        results = model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=sorted(self.classes),
            conf=min(floors),
            device=DEVICE,
            verbose=False,
        )
        if not results:
            return []
        boxes = results[0].boxes
        if boxes is None or boxes.id is None or len(boxes) == 0:
            return []  # objects seen for the first time have no id yet
        ids = np.asarray(boxes.id).reshape(-1)
        cls = np.asarray(boxes.cls).reshape(-1)
        conf = np.asarray(boxes.conf).reshape(-1)
        xyxy = np.asarray(boxes.xyxy).reshape(-1, 4)
        out: list[Detection] = []
        for i in range(len(ids)):
            class_id = int(cls[i])
            if class_id not in self.classes:
                continue
            c = float(conf[i])
            if c < self.class_conf.get(class_id, self.conf_floor):
                continue
            x1, y1, x2, y2 = (int(v) for v in xyxy[i])
            out.append(Detection(int(ids[i]), class_id, c, (x1, y1, x2, y2)))
        return out


class PoseEstimator:
    def __init__(self, model_path: str, model_factory: Callable[[str], object] | None = None) -> None:
        self.model_path = model_path
        self._factory = model_factory or _load_yolo
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            self._model = self._factory(self.model_path)
        return self._model

    def warmup(self) -> None:
        self.estimate(np.zeros((480, 640, 3), dtype=np.uint8))

    def estimate(self, frame) -> list[PosePerson]:
        model = self._ensure_model()
        results = model.predict(frame, device=DEVICE, verbose=False)
        if not results:
            return []
        r = results[0]
        if r.keypoints is None or r.boxes is None or len(r.boxes) == 0:
            return []
        kp = r.keypoints
        xy = np.asarray(kp.xy)
        if xy.ndim != 3 or xy.shape[1] == 0:
            return []
        conf = np.asarray(kp.conf) if kp.conf is not None else np.ones(xy.shape[:2])
        xyxy = np.asarray(r.boxes.xyxy).reshape(-1, 4)
        people: list[PosePerson] = []
        for i in range(xy.shape[0]):
            pts = np.concatenate([xy[i], conf[i].reshape(-1, 1)], axis=1).astype(np.float32)
            x1, y1, x2, y2 = (int(v) for v in xyxy[i])
            people.append(PosePerson((x1, y1, x2, y2), pts))
        return people

    @staticmethod
    def draw(frame, people: list[PosePerson], min_conf: float = 0.5) -> None:
        for person in people:
            pts = person.keypoints
            for a, b in _SKELETON:
                if pts[a, 2] >= min_conf and pts[b, 2] >= min_conf:
                    cv2.line(
                        frame, (int(pts[a, 0]), int(pts[a, 1])), (int(pts[b, 0]), int(pts[b, 1])), (255, 200, 0), 2
                    )
            for x, y, c in pts:
                if c >= min_conf:
                    cv2.circle(frame, (int(x), int(y)), 3, (0, 255, 255), -1)
