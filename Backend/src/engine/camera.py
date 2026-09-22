"""Threaded frame grabber with reconnects, a stall watchdog and file looping.

Only the capture thread touches the ``cv2.VideoCapture`` after start-up:
releasing a capture from another thread while ``read()`` is blocked crashes
the AVFoundation and FFmpeg backends. The one exception is the *first* open
of a local camera on macOS, which happens on the calling thread because the
OS permission prompt can only be raised from the main run loop.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import cv2
import numpy as np

log = logging.getLogger("chanakya.camera")

_URL_SCHEMES = ("rtsp://", "rtsps://", "http://", "https://", "udp://", "tcp://")


def source_label(source) -> str:
    """Human-readable source with credentials, query strings and full paths removed."""
    if isinstance(source, int):
        return f"camera:{source}"
    text = str(source)
    if text.lower().startswith(_URL_SCHEMES):
        parts = urlsplit(text)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme}://{host}{port}{parts.path or ''}"
    return Path(text).name or "stream"


def _is_url(source) -> bool:
    return isinstance(source, str) and source.lower().startswith(_URL_SCHEMES)


class ThreadedCamera:
    def __init__(
        self,
        source,
        *,
        reconnect_delay: float = 3.0,
        capture_factory: Callable | None = None,
        stall_seconds: float = 5.0,
    ) -> None:
        self.source = source
        self.source_label = source_label(source)
        self.reconnect_delay = float(reconnect_delay)
        self.stall_seconds = float(stall_seconds)
        self._factory = capture_factory or self._open_capture

        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture = None
        self._frame: np.ndarray | None = None
        self._seq = 0
        self._last_frame_at: float | None = None
        self._native_fps = 0.0
        self._is_file = False
        self._permission_hint_logged = False

    # ------------------------------------------------------------------ public
    @property
    def online(self) -> bool:
        return self._last_frame_at is not None and (time.monotonic() - self._last_frame_at) <= self.stall_seconds

    @property
    def frame_seq(self) -> int:
        return self._seq

    def start(self) -> ThreadedCamera:
        if self._thread is not None:
            return self
        if isinstance(self.source, int) and sys.platform == "darwin":
            # First open on the calling thread so macOS can show the permission prompt.
            self._capture = self._try_open()
        self._thread = threading.Thread(target=self._run, name=f"camera-{self.source_label}", daemon=True)
        self._thread.start()
        return self

    def read(self, last_seq: int | None = None, timeout: float = 0.0) -> tuple[bool, np.ndarray | None, int]:
        """Latest frame. With ``last_seq``, wait up to ``timeout`` for a NEWER one.

        The frame is copied only when it is new; otherwise ``(ok, None, seq)``
        is returned so callers do not pay for a 900 KB copy per poll.
        """
        with self._cond:
            if last_seq is not None and self._seq <= last_seq and timeout > 0:
                self._cond.wait_for(lambda: self._seq > last_seq or self._stop.is_set(), timeout=timeout)
            ok = self._frame is not None and self.online
            if last_seq is not None and self._seq <= last_seq:
                return ok, None, self._seq
            frame = self._frame.copy() if (ok and self._frame is not None) else None
            return ok, frame, self._seq

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # ------------------------------------------------------------------ capture thread
    def _open_capture(self, source):
        if _is_url(source):
            params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000]
            return cv2.VideoCapture(source, cv2.CAP_FFMPEG, params)
        if isinstance(source, int) and sys.platform == "darwin":
            return cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)
        return cv2.VideoCapture(source)

    def _try_open(self):
        try:
            cap = self._factory(self.source)
        except Exception as exc:  # noqa: BLE001
            log.warning("opening %s failed: %s", self.source_label, type(exc).__name__)
            return None
        if cap is None or not cap.isOpened():
            if isinstance(self.source, int) and sys.platform == "darwin" and not self._permission_hint_logged:
                log.warning(
                    "camera %s did not open: grant Camera permission to your terminal "
                    "(System Settings > Privacy & Security > Camera), then restart",
                    self.source_label,
                )
                self._permission_hint_logged = True
            else:
                log.warning("source %s did not open", self.source_label)
            if cap is not None:
                with contextlib.suppress(Exception):  # a half-open capture may throw on release
                    cap.release()
            return None
        self._is_file = isinstance(self.source, str) and not _is_url(self.source) and os.path.isfile(self.source)
        try:
            self._native_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) if self._is_file else 0.0
        except Exception:  # noqa: BLE001
            self._native_fps = 0.0
        log.info("source %s online", self.source_label)
        return cap

    def _run(self) -> None:
        cap = self._capture
        next_deadline = time.monotonic()
        while not self._stop.is_set():
            if cap is None:
                cap = self._try_open()
                if cap is None:
                    self._stop.wait(self.reconnect_delay)
                    continue
            try:
                ok, frame = cap.read()
            except Exception as exc:  # noqa: BLE001
                log.warning("read from %s raised %s", self.source_label, type(exc).__name__)
                ok, frame = False, None
            if not ok or frame is None:
                if self._is_file and self._seek_start(cap):
                    continue  # demo clips loop forever and are never "offline"
                log.warning("source %s lost; reconnecting in %.0fs", self.source_label, self.reconnect_delay)
                self._release(cap)
                cap = None
                self._stop.wait(self.reconnect_delay)
                continue
            with self._cond:
                self._frame = frame
                self._seq += 1
                self._last_frame_at = time.monotonic()
                self._cond.notify_all()
            if self._is_file and self._native_fps > 0:
                next_deadline += 1.0 / self._native_fps
                delay = next_deadline - time.monotonic()
                if delay > 0:
                    self._stop.wait(delay)
                else:
                    next_deadline = time.monotonic()
            else:
                time.sleep(0.001)
        self._release(cap)
        self._capture = None

    @staticmethod
    def _seek_start(cap) -> bool:
        try:
            return bool(cap.set(cv2.CAP_PROP_POS_FRAMES, 0))
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _release(cap) -> None:
        if cap is None:
            return
        with contextlib.suppress(Exception):  # backends can throw on release after a lost stream
            cap.release()
