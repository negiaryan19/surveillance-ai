"""Black-box clip recorder: pre-roll + post-roll around an incident (one per camera).

Frames are buffered as JPEG bytes rather than raw arrays — ~40 MB instead of
~276 MB per camera for 10 s at 640x480 — and the buffer therefore never aliases
the worker's frame, so drawing on the frame afterwards cannot leak into a clip.
Output is H.264 when the OpenCV build can write it (browsers play it inline);
otherwise mp4v is written and transcoded with ffmpeg when available.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess  # nosec B404
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("chanakya.video_recorder")

_PREFIX_RE = re.compile(r"[^A-Za-z0-9_-]+")
MIN_FPS, MAX_FPS = 5.0, 30.0


class VideoRecorder:
    def __init__(
        self,
        output_dir=None,
        pre_buffer_sec: float = 5,
        post_buffer_sec: float = 5,
        max_buffer_frames: int = 300,
        jpeg_quality: int = 90,
    ) -> None:
        if output_dir is None:
            from config import settings

            output_dir = settings.VIDEOS_DIR
        self.output_dir = Path(output_dir)
        self.pre_buffer_sec = float(pre_buffer_sec)
        self.post_buffer_sec = float(post_buffer_sec)
        self.max_buffer_frames = int(max_buffer_frames)
        self.jpeg_quality = int(jpeg_quality)

        self._lock = threading.Lock()
        self._pre: deque[tuple[float, bytes]] = deque()
        self._post: list[tuple[float, bytes]] = []
        self._pending: list[Callable[[str], None]] = []
        self._prefix = ""
        self._trigger_time: float | None = None
        self._writers: list[threading.Thread] = []
        self.recording_active = False
        self.disabled = False

    # ------------------------------------------------------------------ input
    def update(self, frame, now: float | None = None) -> None:
        if frame is None:
            return
        now = time.time() if now is None else float(now)
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        if not ok:
            return
        entry = (now, buf.tobytes())
        with self._lock:
            if self.recording_active:
                self._post.append(entry)
                if len(self._post) > self.max_buffer_frames:
                    self._post.pop(0)
            else:
                self._pre.append(entry)
                while self._pre and (now - self._pre[0][0]) > self.pre_buffer_sec:
                    self._pre.popleft()
                while len(self._pre) > self.max_buffer_frames:
                    self._pre.popleft()
        self.flush(now)

    def trigger(self, prefix: str, on_saved: Callable[[str], None] | None = None, now: float | None = None) -> bool:
        """Start (or join) a recording. Returns False only when recording is disabled.

        The trigger time lives in the same time base as ``update()``: when
        ``now`` is not given, the newest buffered frame's timestamp is used, so
        an injected clock in tests and the wall clock in production both work.
        """
        if self.disabled:
            return False
        with self._lock:
            if on_saved is not None:
                self._pending.append(on_saved)
            if self.recording_active:
                return True  # a second incident inside the window shares the clip
            self.recording_active = True
            self._prefix = _PREFIX_RE.sub("_", str(prefix)).strip("_") or "incident"
            if now is None:
                now = self._pre[-1][0] if self._pre else time.time()
            self._trigger_time = float(now)
            self._post = []
        log.info("recording %s (pre-roll %d frames)", self._prefix, len(self._pre))
        return True

    def flush(self, now: float | None = None) -> None:
        """Finish the recording once the post-roll has elapsed (also when frames stop)."""
        now = time.time() if now is None else float(now)
        with self._lock:
            if not self.recording_active or self._trigger_time is None:
                return
            if now - self._trigger_time < self.post_buffer_sec:
                return
            frames = list(self._pre) + self._post
            prefix, callbacks = self._prefix, self._pending
            self.recording_active = False
            self._trigger_time = None
            self._post = []
            self._pending = []
            self._pre.clear()
        # Non-daemon so an interpreter exit does not truncate a half-written clip.
        thread = threading.Thread(
            target=self._write, args=(frames, prefix, callbacks), daemon=False, name="clip-writer"
        )
        with self._lock:
            self._writers = [t for t in self._writers if t.is_alive()] + [thread]
        thread.start()

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until pending clip writes finish (used on shutdown). Returns True if none remain."""
        deadline = time.monotonic() + timeout
        with self._lock:
            writers = list(self._writers)
        for t in writers:
            t.join(timeout=max(0.0, deadline - time.monotonic()))
        return not any(t.is_alive() for t in writers)

    # ------------------------------------------------------------------ output
    def _write(self, frames: list[tuple[float, bytes]], prefix: str, callbacks: list[Callable]) -> None:
        path: str | None = None
        try:
            if frames:
                path = self._write_frames(frames, prefix)
        except Exception:  # noqa: BLE001
            log.exception("clip write failed")
        if path is None:
            return
        for cb in callbacks:
            try:
                cb(path)
            except Exception:  # noqa: BLE001
                log.exception("clip callback failed")

    def _write_frames(self, frames: list[tuple[float, bytes]], prefix: str) -> str | None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final = self.output_dir / f"{prefix}_{stamp}.mp4"
        fps = _fps_from_timestamps([t for t, _ in frames])
        first = cv2.imdecode(np.frombuffer(frames[0][1], np.uint8), cv2.IMREAD_COLOR)
        if first is None:
            return None
        h, w = first.shape[:2]

        if self._encode(frames, final, "avc1", fps, (w, h)):
            return str(final.resolve())
        # Fallback: mp4v is not browser-playable; transcode with ffmpeg when we can.
        tmp = final.with_name(final.stem + "_mp4v.mp4")
        if not self._encode(frames, tmp, "mp4v", fps, (w, h)):
            return None
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            cmd = [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(tmp),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(final),
            ]
            try:
                # argv list built from our own paths; never a shell.
                result = subprocess.run(cmd, capture_output=True, timeout=120, check=False)  # nosec B603
                if result.returncode == 0 and final.is_file() and final.stat().st_size > 0:
                    tmp.unlink(missing_ok=True)
                    return str(final.resolve())
            except Exception:  # noqa: BLE001
                log.exception("ffmpeg transcode failed")
        tmp.replace(final)
        return str(final.resolve())

    @staticmethod
    def _encode(frames, path: Path, fourcc: str, fps: float, size: tuple[int, int]) -> bool:
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), fps, size)
        if not writer.isOpened():
            writer.release()
            path.unlink(missing_ok=True)
            return False
        for _, jpeg in frames:
            img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            if img.shape[1] != size[0] or img.shape[0] != size[1]:
                img = cv2.resize(img, size)
            writer.write(img)
        writer.release()
        ok = path.is_file() and path.stat().st_size > 1024
        if not ok:
            path.unlink(missing_ok=True)
        return ok


def _fps_from_timestamps(times: list[float]) -> float:
    if len(times) < 2:
        return 15.0
    span = times[-1] - times[0]
    if span <= 0:
        return 15.0
    return float(max(MIN_FPS, min(MAX_FPS, (len(times) - 1) / span)))
