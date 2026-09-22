import logging

import cv2
import numpy as np
import pytest

from src import telegram_bot
from src.anomaly_detector import AnomalyDetector
from src.video_recorder import VideoRecorder


# ------------------------------------------------------------------ anomaly
def walk(detector, fps, speed_bh_per_s, seconds=4.0, bbox_h=200):
    """Feed a straight walk at `speed_bh_per_s` body-heights/second; return the last verdict."""
    x = 0.0
    verdict = (False, None, None)
    for i in range(int(seconds * fps)):
        t = i / fps
        x += speed_bh_per_s * bbox_h / fps
        verdict = detector.analyze(1, (x, 0, x + 80, bbox_h), (x + 40, 100), now=t)
    return verdict


@pytest.mark.parametrize("fps", [6, 15, 30])
def test_same_motion_same_verdict_at_any_fps(fps):
    assert walk(AnomalyDetector(2.0, 1.2), fps, 1.0) == (False, None, None)
    assert walk(AnomalyDetector(2.0, 1.2), fps, 3.0)[:2] == (True, "RUNNING")


def test_erratic_movement_and_prune():
    d = AnomalyDetector(2.0, 1.2)
    x = 0.0
    v = None
    for i in range(60):
        t = i / 15
        x += (600 if i % 2 else 5) / 15  # alternating sprint (3 bh/s) / crawl steps
        v = d.analyze(1, (x, 0, x + 80, 200), (x, 100), now=t)
    assert v[:2] == (True, "ERRATIC")
    d.analyze(2, (0, 0, 80, 200), (0, 0), now=0)
    d.prune([2])
    assert len(d) == 1


def test_needs_samples_and_span_and_skips_gaps():
    d = AnomalyDetector(2.0, 1.2, min_samples=10, min_span_s=2.0)
    for i in range(10):  # 10 samples but only 0.6 s of span
        d.analyze(1, (0, 0, 80, 200), (i * 100.0, 0), now=i / 15)
    assert d.analyze(1, (0, 0, 80, 200), (2000.0, 0), now=11 / 15)[0] is False
    assert d.analyze(1, (0, 0, 80, 200), (9999.0, 0), now=60.0)[0] is False  # dt > 1 s skipped


# ------------------------------------------------------------------ recorder
def frames(n, w=64, h=48):
    for i in range(n):
        f = np.zeros((h, w, 3), np.uint8)
        f[:, : (i * 3) % w] = (0, 0, 255)
        yield f


def test_recorder_writes_playable_clip_and_calls_every_callback(tmp_path):
    rec = VideoRecorder(tmp_path, pre_buffer_sec=0.5, post_buffer_sec=0.5)
    fps = 10
    saved = []
    t = 0.0
    for i, f in enumerate(frames(40)):
        rec.update(f, now=t)
        if i == 15:
            assert rec.trigger("incident_1", saved.append) is True
        if i == 17:
            assert rec.trigger("incident_2", saved.append) is True  # joins the same recording
        t += 1 / fps
    assert rec.wait_idle(10)
    assert len(saved) == 2 and saved[0] == saved[1]
    cap = cv2.VideoCapture(saved[0])
    assert cap.isOpened()
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    assert 8 <= n <= 14  # ~0.5 s pre + ~0.5 s post at 10 fps
    assert saved[0].endswith(".mp4") and "incident_1_" in saved[0]


def test_flush_finishes_a_recording_when_frames_stop(tmp_path):
    rec = VideoRecorder(tmp_path, pre_buffer_sec=0.5, post_buffer_sec=0.5)
    for i, f in enumerate(frames(5)):
        rec.update(f, now=i / 10)
    rec.trigger("stuck", None)
    assert rec.recording_active
    rec.flush(now=100.0)
    assert not rec.recording_active and rec.wait_idle(10)
    assert list(tmp_path.glob("stuck_*.mp4"))


def test_callback_exception_does_not_kill_writer(tmp_path, caplog):
    rec = VideoRecorder(tmp_path, pre_buffer_sec=0.2, post_buffer_sec=0.2)
    got = []

    def boom(path):
        raise RuntimeError("cb")

    for i, f in enumerate(frames(10)):
        rec.update(f, now=i / 10)
        if i == 3:
            rec.trigger("x", boom)
            rec.trigger("x", got.append)
    assert rec.wait_idle(10) and len(got) == 1


def test_prefix_sanitised_and_buffer_bounded(tmp_path):
    rec = VideoRecorder(tmp_path, pre_buffer_sec=100, post_buffer_sec=0.1, max_buffer_frames=5)
    for i, f in enumerate(frames(20)):
        rec.update(f, now=i / 10)
    assert len(rec._pre) == 5
    rec.trigger("../evil name!", None)
    assert rec._prefix == "evil_name"


def test_ffmpeg_fallback_when_avc1_unavailable(tmp_path, monkeypatch):
    rec = VideoRecorder(tmp_path, pre_buffer_sec=0.2, post_buffer_sec=0.2)
    real_encode = VideoRecorder._encode
    calls = []

    def encode(frames_, path, fourcc, fps, size):
        calls.append(fourcc)
        if fourcc == "avc1":
            return False
        return real_encode(frames_, path, fourcc, fps, size)

    ran = []
    monkeypatch.setattr(VideoRecorder, "_encode", staticmethod(encode))
    monkeypatch.setattr("src.video_recorder.shutil.which", lambda name: "/usr/bin/ffmpeg")

    def fake_run(cmd, **kw):
        ran.append(cmd)
        from pathlib import Path

        Path(cmd[-1]).write_bytes(b"x" * 2048)

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr("src.video_recorder.subprocess.run", fake_run)
    got = []
    for i, f in enumerate(frames(8)):
        rec.update(f, now=i / 10)
        if i == 2:
            rec.trigger("fb", got.append)
    assert rec.wait_idle(10)
    assert calls == ["avc1", "mp4v"] and ran and "libx264" in ran[0] and got and got[0].endswith(".mp4")
    assert not list(tmp_path.glob("*_mp4v.mp4"))


# ------------------------------------------------------------------ telegram
@pytest.fixture
def sync_thread(monkeypatch):
    """Run the alert thread inline so tests can assert on its effects."""

    class Inline:
        def __init__(self, target=None, args=(), **kw):
            self._t, self._a = target, args

        def start(self):
            self._t(*self._a)

    monkeypatch.setattr(telegram_bot.threading, "Thread", Inline)


def test_unconfigured_returns_false_and_warns_once(monkeypatch, caplog):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(telegram_bot, "_warned_unconfigured", False)
    with caplog.at_level(logging.WARNING):
        assert telegram_bot.send_telegram_alert("x", 90) is False
        assert telegram_bot.send_telegram_alert("x", 90) is False
    assert sum("disabled" in r.message for r in caplog.records) == 1
    assert telegram_bot.telegram_configured() is False


def test_sends_photo_with_caption(monkeypatch, sync_thread, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    snap = tmp_path / "s.jpg"
    snap.write_bytes(b"jpeg")
    posts = []

    class Resp:
        status_code = 200

    def post(url, **kw):
        posts.append((url, kw))
        return Resp()

    monkeypatch.setattr("requests.post", post)
    assert telegram_bot.send_telegram_alert("Person ID:3 (ALPHA)", 90, str(snap), extra="Unknown Identity") is True
    assert len(posts) == 1 and posts[0][0].endswith("/sendPhoto")
    assert posts[0][1]["data"]["chat_id"] == "42" and "90%" in posts[0][1]["data"]["caption"]
    assert "Unknown Identity" in posts[0][1]["data"]["caption"]
    posts.clear()
    telegram_bot.send_telegram_alert("x", 80, None)
    assert posts[0][0].endswith("/sendMessage") and posts[0][1]["json"]["chat_id"] == "42"


def test_exception_text_with_token_is_never_logged(monkeypatch, sync_thread, caplog):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "ABC123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    import requests

    def post(url, **kw):
        raise requests.ConnectionError("Max retries exceeded with url: /botABC123/sendMessage")

    monkeypatch.setattr("requests.post", post)
    with caplog.at_level(logging.DEBUG):
        telegram_bot.send_telegram_alert("x", 80)
    assert "ABC123" not in caplog.text and "ConnectionError" in caplog.text


def test_http_error_logs_description_not_url(monkeypatch, sync_thread, caplog):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "SECRET9")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    class Resp:
        status_code = 400

        @staticmethod
        def json():
            return {"description": "chat not found"}

    monkeypatch.setattr("requests.post", lambda url, **kw: Resp())
    with caplog.at_level(logging.WARNING):
        telegram_bot.send_telegram_alert("x", 80)
    assert "chat not found" in caplog.text and "SECRET9" not in caplog.text
