"""Evaluation harness: scoring logic (fast) and the real replay on the fixture (slow)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.evaluate import compare, evaluate, iou, match_frame, to_markdown

BACKEND = Path(__file__).resolve().parent.parent
BASELINE = BACKEND / "eval" / "baselines" / "v2.0.0.json"


def track(tid, bbox, cls=0):
    return {"track_id": tid, "class_id": cls, "bbox": list(bbox)}


def test_iou_and_greedy_matching():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    labels = [{"bbox": [0, 0, 100, 200]}, {"bbox": [300, 0, 400, 200]}]
    tracks = [track(1, (5, 5, 100, 200)), track(2, (600, 0, 700, 200)), track(3, (2, 0, 98, 205))]
    tp, fp, fn, pairs = match_frame(labels, tracks)
    assert tp == 1 and fp == 2 and fn == 1 and pairs == [(0, 3)] or pairs == [(0, 1)]


def test_ignore_labels_are_neither_misses_nor_false_positives():
    labels = [{"bbox": [0, 0, 40, 300], "ignore": True}, {"bbox": [100, 0, 200, 300]}]
    tp, fp, fn, _ = match_frame(labels, [track(1, (0, 0, 42, 300)), track(2, (100, 0, 200, 300))])
    assert (tp, fp, fn) == (1, 0, 0)
    tp, fp, fn, _ = match_frame(labels, [])
    assert (tp, fp, fn) == (0, 0, 1)


def test_scorecard_metrics_and_events():
    labels = {
        "frames": {
            "0": [{"label_id": "a", "bbox": [0, 0, 100, 200]}],
            "1": [{"label_id": "a", "bbox": [0, 0, 100, 200]}],
            "2": [{"label_id": "a", "bbox": [0, 0, 100, 200]}],
        },
        "events": [{"zone": None, "start": 0, "end": 2}, {"zone": "CRITICAL", "start": 50, "end": 60}],
        "event_tolerance_frames": 1,
    }
    run = [
        {"frame": 0, "tracks": [track(1, (0, 0, 100, 200))], "incidents": [{"id": 1, "zone": "WARNING"}]},
        {"frame": 1, "tracks": [track(2, (0, 0, 100, 200)), track(9, (500, 0, 600, 100))]},  # id switch + FP
        {"frame": 2, "tracks": [], "incidents": [{"id": 2, "zone": "WARNING"}]},  # miss + stray alert far from event 2
    ]
    card = evaluate(run, labels, {"fps_processed": 12.5})
    assert (card["detection_tp"], card["detection_fp"], card["detection_fn"]) == (2, 1, 1)
    assert card["detection_precision"] == pytest.approx(66.7) and card["detection_recall"] == pytest.approx(66.7)
    assert card["identity_switches"] == 1
    assert card["events_hit"] == 1 and card["events_expected"] == 2
    assert card["incidents"] == 2 and card["false_alerts"] == 0  # both incidents fall inside event 1's window
    assert card["alert_recall"] == 50.0 and card["fps_processed"] == 12.5
    assert "| Detection recall |" in to_markdown(card)


def test_compare_flags_only_drops_beyond_tolerance():
    base = {"detection_recall": 90.0, "detection_precision": 80.0, "alert_recall": 100.0, "alert_precision": 50.0}
    assert compare({**base, "detection_recall": 88.5}, base, 2.0) == []
    assert compare({**base, "detection_recall": 87.0, "alert_precision": 70.0}, base, 2.0) == [
        "detection_recall: 90.0 -> 87.0"
    ]


@pytest.mark.slow
def test_fixture_replay_matches_baseline(tmp_path):
    pytest.importorskip("ultralytics")
    pytest.importorskip("face_recognition")
    py = sys.executable
    run = subprocess.run(
        [py, "-m", "tools.make_fixture", "--out-dir", str(tmp_path)],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert run.returncode == 0, run.stderr
    clip, labels = tmp_path / "pan_demo.mp4", tmp_path / "pan_demo.labels.json"
    out = tmp_path / "run.jsonl"
    run = subprocess.run(
        [py, "-m", "tools.replay", "--clip", str(clip), "--out", str(out), "--data-dir", str(tmp_path / "data")],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert run.returncode == 0, run.stderr
    args = [
        py,
        "-m",
        "tools.evaluate",
        "--run",
        str(out),
        "--labels",
        str(labels),
        "--out",
        str(tmp_path / "card.json"),
    ]
    if BASELINE.is_file():
        args += ["--baseline", str(BASELINE), "--tolerance", "3"]
    run = subprocess.run(args, cwd=BACKEND, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    card = json.loads((tmp_path / "card.json").read_text())
    assert card["frames"] == 180 and card["detection_recall"] > 50 and card["events_hit"] >= 1
