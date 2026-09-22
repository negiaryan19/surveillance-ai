"""Short-horizon movement prediction per track (one instance per camera)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

import numpy as np


class MovementPredictor:
    def __init__(self, max_history: int = 10) -> None:
        self.history: dict[int, list[tuple[float, float]]] = defaultdict(list)
        self.max_history = int(max_history)

    def update(self, person_id: int, x: float, y: float) -> None:
        hist = self.history[person_id]
        hist.append((float(x), float(y)))
        if len(hist) > self.max_history:
            hist.pop(0)

    def predict_next_position(self, person_id: int, frames_ahead: int = 15) -> tuple[int, int] | None:
        positions = self.history.get(person_id, [])
        if len(positions) < 3:
            return None
        arr = np.asarray(positions)
        avg_v = np.diff(arr, axis=0).mean(axis=0)
        last = arr[-1]
        return int(last[0] + avg_v[0] * frames_ahead), int(last[1] + avg_v[1] * frames_ahead)

    def get_direction(self, person_id: int) -> str:
        positions = self.history.get(person_id, [])
        if len(positions) < 5:
            return "Analyzing"
        (sx, sy), (ex, ey) = positions[0], positions[-1]
        dx, dy = ex - sx, ey - sy
        if abs(dx) < 10 and abs(dy) < 10:
            return "Stationary"
        if abs(dx) > abs(dy):
            return "East ->" if dx > 0 else "<- West"
        return "South v" if dy > 0 else "North ^"

    def prune(self, active_ids: Iterable[int]) -> None:
        keep = set(active_ids)
        for pid in [pid for pid in self.history if pid not in keep]:
            del self.history[pid]
