"""Security zones: normalised rectangles per camera, JSON-persisted.

Rectangles are stored in 0..1 coordinates so one zone file works for any
stream resolution. Each camera may have its own set; cameras without one use
the ``"default"`` set.

Concurrency model: the whole zone table is an immutable mapping of immutable
tuples of frozen dataclasses. Writers build a new table, persist it, and swap
the reference under an ``RLock``; readers (camera threads call ``level_at`` for
every detection of every frame) only grab the current reference.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("chanakya.zones")

LEVELS = ("SAFE", "PERIMETER", "WARNING", "CRITICAL")  # ascending priority
LEVEL_COLORS_BGR = {
    "SAFE": (0, 255, 0),
    "PERIMETER": (255, 200, 0),
    "WARNING": (0, 165, 255),
    "CRITICAL": (0, 0, 255),
}

DEFAULT_CAMERA_ID = "default"
MAX_ZONES_PER_CAMERA = 12
MAX_NAME_LENGTH = 40

_CAMERA_ID_RE = re.compile(r"[a-z0-9_-]{1,32}")
_ZONE_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
_PRIORITY = {level: rank for rank, level in enumerate(LEVELS)}


@dataclass(frozen=True)
class SecurityZone:
    """One rectangle, in normalised coordinates, with a security level."""

    id: str
    name: str
    level: str
    rect: tuple[float, float, float, float]

    def contains(self, nx: float, ny: float) -> bool:
        """Edges are inclusive, so a point on a shared border belongs to both
        neighbours and ``level_at`` resolves it to the higher-priority one."""
        x1, y1, x2, y2 = self.rect
        return x1 <= nx <= x2 and y1 <= ny <= y2

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "level": self.level, "rect": list(self.rect)}


def _default_zones() -> tuple[SecurityZone, ...]:
    """Left-to-right slices: the v1 layout, expressed in normalised coordinates."""
    return (
        SecurityZone("safe", "Safe", "SAFE", (0.0, 0.0, 0.4, 1.0)),
        SecurityZone("warning", "Warning", "WARNING", (0.4, 0.0, 0.75, 1.0)),
        SecurityZone("critical", "Critical", "CRITICAL", (0.75, 0.0, 1.0, 1.0)),
    )


def _validate_camera_id(camera_id) -> str:
    if not isinstance(camera_id, str) or not _CAMERA_ID_RE.fullmatch(camera_id):
        raise ValueError("camera_id must be 1-32 characters from a-z, 0-9, '_' and '-'")
    return camera_id


def _validate_name(raw, where: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{where}: name must be a string")
    name = raw.strip()
    if not 1 <= len(name) <= MAX_NAME_LENGTH:
        raise ValueError(f"{where}: name must be 1-{MAX_NAME_LENGTH} characters")
    if not name.isprintable():
        raise ValueError(f"{where}: name must not contain control characters")
    return name


def _validate_rect(raw, where: str) -> tuple[float, float, float, float]:
    """Four finite numbers with ``0 <= x1 < x2 <= 1`` and ``0 <= y1 < y2 <= 1``.

    ``json.loads`` happily produces NaN, Infinity and booleans, and ``True``
    passes ``isinstance(v, int)``; all three would poison every later
    comparison, so the type check is exact and finiteness is explicit.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise ValueError(f"{where}: rect must be [x1, y1, x2, y2]")
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in raw):
        raise ValueError(f"{where}: rect values must be finite numbers")
    x1, y1, x2, y2 = (float(value) for value in raw)
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        raise ValueError(f"{where}: rect must satisfy 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1")
    return (x1, y1, x2, y2)


def _fresh_id(taken: set[str]) -> str:
    while True:
        candidate = uuid.uuid4().hex[:12]
        if candidate not in taken:
            return candidate


def validate_zones(zones) -> tuple[SecurityZone, ...]:
    """Validate client-supplied zone dicts; raises ``ValueError`` with a usable message.

    Unknown keys are dropped. A client ``id`` is kept only when it is
    well-formed and not already used in this list; otherwise the zone gets a
    fresh id (the first holder of a duplicated id keeps it).
    """
    if not isinstance(zones, list):
        raise ValueError("zones must be a list")
    if len(zones) > MAX_ZONES_PER_CAMERA:
        raise ValueError(f"at most {MAX_ZONES_PER_CAMERA} zones per camera")
    validated: list[SecurityZone] = []
    taken: set[str] = set()
    for index, raw in enumerate(zones):
        where = f"zone {index}"
        if not isinstance(raw, dict):
            raise ValueError(f"{where}: must be an object")
        level = raw.get("level")
        if not isinstance(level, str) or level not in LEVELS:
            raise ValueError(f"{where}: level must be one of {', '.join(LEVELS)}")
        name = _validate_name(raw.get("name"), where)
        rect = _validate_rect(raw.get("rect"), where)
        zone_id = raw.get("id")
        if not isinstance(zone_id, str) or not _ZONE_ID_RE.fullmatch(zone_id) or zone_id in taken:
            zone_id = _fresh_id(taken)
        taken.add(zone_id)
        validated.append(SecurityZone(zone_id, name, level, rect))
    return tuple(validated)


class ZoneManager:
    """Thread-safe, persisted table of security zones per camera."""

    def __init__(self, zones_file=None):
        """``zones_file`` None resolves to ``settings.ZONES_FILE``.

        A missing file is the normal first run; a corrupt one is logged as a
        warning. Both start from the built-in defaults, and nothing is written
        until the first ``set_zones``.
        """
        if zones_file is None:
            from config import settings

            zones_file = settings.ZONES_FILE
        self._file = Path(zones_file)
        self._lock = threading.RLock()
        self._table: dict[str, tuple[SecurityZone, ...]] = self._load()

    # ------------------------------------------------------------------ #
    # persistence
    # ------------------------------------------------------------------ #
    def _load(self) -> dict[str, tuple[SecurityZone, ...]]:
        table = {DEFAULT_CAMERA_ID: _default_zones()}
        try:
            with open(self._file, encoding="utf-8") as handle:
                stored = json.load(handle)
        except FileNotFoundError:
            logger.info("No zones file yet; using the default zones")
            return table
        except (OSError, ValueError, RecursionError) as exc:
            logger.warning("Zones file unreadable (%s); using the default zones", type(exc).__name__)
            return table
        if not isinstance(stored, dict):
            logger.warning("Zones file is not a JSON object; using the default zones")
            return table
        for camera_id, raw_zones in stored.items():
            try:
                zones = validate_zones(raw_zones)
                if not zones:
                    raise ValueError("empty zone set")
                table[_validate_camera_id(camera_id)] = zones
            except ValueError as exc:
                # One bad entry must not discard the operator's other cameras.
                logger.warning("Ignoring an invalid zone set in the zones file: %s", exc)
        return table

    def _persist(self, table: dict[str, tuple[SecurityZone, ...]]) -> None:
        """Write-then-rename so a crash mid-write never leaves a truncated file."""
        payload = {camera: [zone.to_dict() for zone in zones] for camera, zones in table.items()}
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._file.with_name(self._file.name + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self._file)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------ #
    # API
    # ------------------------------------------------------------------ #
    def get_zones(self, camera_id) -> list[SecurityZone]:
        """The camera's own zone set, else the ``"default"`` set."""
        with self._lock:
            table = self._table
        return list(table.get(camera_id) or table[DEFAULT_CAMERA_ID])

    def set_zones(self, camera_id, zones: list[dict]) -> list[SecurityZone]:
        """Replace a camera's zones and persist; returns the zones now in effect.

        An empty list deletes the camera-specific set (the camera falls back to
        ``"default"``); the default set itself can never be emptied. The file
        is written BEFORE the in-memory table is swapped, so a failed write
        (``OSError``) leaves memory and disk agreeing on the old zones.
        """
        camera_id = _validate_camera_id(camera_id)
        validated = validate_zones(zones)
        if not validated and camera_id == DEFAULT_CAMERA_ID:
            raise ValueError("the default zone set cannot be empty")
        with self._lock:
            table = dict(self._table)
            if validated:
                table[camera_id] = validated
            else:
                table.pop(camera_id, None)
            self._persist(table)
            self._table = table
        return self.get_zones(camera_id)

    def level_at(self, camera_id, x, y, frame_w, frame_h) -> str:
        """Level of the highest-priority zone containing pixel ``(x, y)``; "SAFE" if none."""
        if frame_w <= 0 or frame_h <= 0:
            return "SAFE"
        nx, ny = x / frame_w, y / frame_h
        best = "SAFE"
        for zone in self.get_zones(camera_id):
            if _PRIORITY[zone.level] > _PRIORITY[best] and zone.contains(nx, ny):
                best = zone.level
        return best

    def draw(self, frame, camera_id) -> None:
        """Outline and label the camera's zones on ``frame`` (in place)."""
        import cv2

        height, width = frame.shape[:2]
        for zone in self.get_zones(camera_id):
            x1, y1, x2, y2 = zone.rect
            top_left = (int(x1 * (width - 1)), int(y1 * (height - 1)))
            bottom_right = (int(x2 * (width - 1)), int(y2 * (height - 1)))
            color = LEVEL_COLORS_BGR[zone.level]
            cv2.rectangle(frame, top_left, bottom_right, color, 2)
            # OpenCV's Hershey fonts are ASCII-only; anything else renders as "?".
            label = f"{zone.name} [{zone.level}]".encode("ascii", "replace").decode("ascii")
            cv2.putText(
                frame,
                label,
                (top_left[0] + 8, top_left[1] + 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )

    def to_dict(self) -> dict:
        """``{"default": [...], "<camera_id>": [...]}`` -- also the file format."""
        with self._lock:
            table = self._table
        return {camera: [zone.to_dict() for zone in zones] for camera, zones in table.items()}
