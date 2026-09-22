"""Posture from pose keypoints (pure numpy).

v1 called anyone whose bounding box was wider than tall "crawling", which is
also true of a person sitting close to a webcam. Here the torso vector
(mid-hip → mid-shoulder) decides: it must be confidently visible, long enough
to be meaningful, and tilted more than 55° from vertical. A bending person
keeps a tall box, so PRONE additionally requires a wide box when one is given.
"""

from __future__ import annotations

import math

import numpy as np

L_SHOULDER, R_SHOULDER, L_HIP, R_HIP = 5, 6, 11, 12
PRONE_ANGLE = 55.0
MIN_TORSO_FRACTION = 0.15
PRONE_MIN_ASPECT = 0.9


def posture_from_keypoints(kpts, bbox=None, min_conf: float = 0.5) -> str:
    pts = np.asarray(kpts, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 13 or pts.shape[1] < 3:
        return "UNKNOWN"
    needed = (L_SHOULDER, R_SHOULDER, L_HIP, R_HIP)
    if any(pts[i, 2] < min_conf for i in needed):
        return "UNKNOWN"
    shoulder = (pts[L_SHOULDER, :2] + pts[R_SHOULDER, :2]) / 2.0
    hip = (pts[L_HIP, :2] + pts[R_HIP, :2]) / 2.0
    dx, dy = shoulder - hip
    length = math.hypot(dx, dy)
    if bbox is not None:
        bw = max(1.0, float(bbox[2]) - float(bbox[0]))
        bh = max(1.0, float(bbox[3]) - float(bbox[1]))
        if length < MIN_TORSO_FRACTION * max(bw, bh):
            return "UNKNOWN"  # torso seen end-on: its angle is noise
    elif length <= 1e-6:
        return "UNKNOWN"
    angle = math.degrees(math.atan2(abs(dx), abs(dy)))  # 0 = vertical, 90 = horizontal
    if angle > PRONE_ANGLE:
        if bbox is None or bw >= PRONE_MIN_ASPECT * bh:
            return "PRONE"
        return "UPRIGHT"
    return "UPRIGHT"


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def match_pose_to_bbox(bbox, people, min_iou: float = 0.3):
    best, best_iou = None, min_iou
    for person in people or ():
        score = _iou(bbox, person.bbox)
        if score >= best_iou:
            best, best_iou = person, score
    return best
