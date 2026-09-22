"""Score a replay run against labels and produce a scorecard.

Usage:
    python -m tools.evaluate --run run.jsonl --labels labels.json --out scorecard.json
                             [--baseline eval/baselines/v2.0.0.json --tolerance 2]

Labels format (``labels.json``)::

    {
      "fps": 15,
      "frames": {"0": [{"bbox": [x1, y1, x2, y2], "class": "Person", "identity": null}], ...},
      "events": [{"type": "intrusion", "zone": "CRITICAL", "start": 12, "end": 40}]
    }

Metrics:
  * detection precision / recall / F1 for persons at IoU >= 0.5, per frame
  * identity switches: labeled persons that were covered by more than one track id
  * alert precision / recall: an expected event is hit when an incident with the
    same zone is logged inside [start - tol, end + tol] frames; incidents that
    match no event are false alerts
  * processed FPS from the replay summary

With ``--baseline`` the exit code is 1 when any headline metric dropped by more
than ``--tolerance`` points, which is how CI blocks accuracy regressions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HEADLINE = ("detection_recall", "detection_precision", "alert_recall", "alert_precision")
EVENT_TOLERANCE_FRAMES = 15


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def load_run(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def match_frame(
    labels: list[dict], tracks: list[dict], threshold: float = 0.5
) -> tuple[int, int, int, list[tuple[int, int]]]:
    """Greedy IoU matching; returns (tp, fp, fn, [(label_index, track_id)]).

    Labels flagged ``ignore`` (people cut off by the frame edge) are neither
    misses nor, when a track overlaps them, false positives.
    """
    ignored = [lab for lab in labels if lab.get("ignore")]
    labels = [lab for lab in labels if not lab.get("ignore")]
    tracks = [t for t in tracks if not any(iou(lab["bbox"], t["bbox"]) >= 0.3 for lab in ignored)]
    candidates = []
    for li, lab in enumerate(labels):
        for track in tracks:
            score = iou(lab["bbox"], track["bbox"])
            if score >= threshold:
                candidates.append((score, li, track["track_id"]))
    candidates.sort(reverse=True)
    used_labels: set[int] = set()
    used_tracks: set[int] = set()
    pairs = []
    for _, li, tid in candidates:
        if li in used_labels or tid in used_tracks:
            continue
        used_labels.add(li)
        used_tracks.add(tid)
        pairs.append((li, tid))
    tp = len(pairs)
    return tp, len(tracks) - tp, len(labels) - tp, pairs


def evaluate(run: list[dict], labels: dict, summary: dict | None) -> dict:
    frames = labels.get("frames", {})
    tp = fp = fn = 0
    id_history: dict[str, set[int]] = {}
    for record in run:
        frame_labels = [lab for lab in frames.get(str(record["frame"]), []) if lab.get("class", "Person") == "Person"]
        persons = [t for t in record.get("tracks", []) if t.get("class_id") == 0]
        f_tp, f_fp, f_fn, pairs = match_frame(frame_labels, persons)
        tp, fp, fn = tp + f_tp, fp + f_fp, fn + f_fn
        for li, tid in pairs:
            key = frame_labels[li].get("label_id") or frame_labels[li].get("identity") or f"label{li}"
            id_history.setdefault(str(key), set()).add(tid)

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    switches = sum(max(0, len(ids) - 1) for ids in id_history.values())

    incidents = [(record["frame"], inc) for record in run for inc in record.get("incidents", [])]
    events = labels.get("events", [])
    tol = labels.get("event_tolerance_frames", EVENT_TOLERANCE_FRAMES)
    hit_events = 0
    matched_incident_ids: set[int] = set()
    for ev in events:
        window = range(ev["start"] - tol, ev["end"] + tol + 1)
        hits = [inc for frame, inc in incidents if frame in window and ev.get("zone") in (None, inc["zone"])]
        if hits:
            hit_events += 1
            matched_incident_ids.update(inc["id"] for inc in hits)
    false_alerts = [inc for _, inc in incidents if inc["id"] not in matched_incident_ids]
    alert_recall = hit_events / len(events) if events else 1.0
    alert_precision = (len(incidents) - len(false_alerts)) / len(incidents) if incidents else 1.0

    return {
        "frames": len(run),
        "detection_tp": tp,
        "detection_fp": fp,
        "detection_fn": fn,
        "detection_precision": round(100 * precision, 1),
        "detection_recall": round(100 * recall, 1),
        "detection_f1": round(100 * f1, 1),
        "identity_switches": switches,
        "events_expected": len(events),
        "events_hit": hit_events,
        "incidents": len(incidents),
        "false_alerts": len(false_alerts),
        "alert_recall": round(100 * alert_recall, 1),
        "alert_precision": round(100 * alert_precision, 1),
        "fps_processed": (summary or {}).get("fps_processed"),
    }


def compare(scorecard: dict, baseline: dict, tolerance: float) -> list[str]:
    regressions = []
    for key in HEADLINE:
        before, after = baseline.get(key), scorecard.get(key)
        if before is None or after is None:
            continue
        if after < before - tolerance:
            regressions.append(f"{key}: {before} -> {after}")
    return regressions


def to_markdown(scorecard: dict) -> str:
    rows = [
        ("Detection precision", f"{scorecard['detection_precision']} %"),
        ("Detection recall", f"{scorecard['detection_recall']} %"),
        ("Detection F1", f"{scorecard['detection_f1']} %"),
        ("Identity switches", str(scorecard["identity_switches"])),
        ("Expected events hit", f"{scorecard['events_hit']} / {scorecard['events_expected']}"),
        ("Incidents logged", str(scorecard["incidents"])),
        ("False alerts", str(scorecard["false_alerts"])),
        ("Alert recall", f"{scorecard['alert_recall']} %"),
        ("Alert precision", f"{scorecard['alert_precision']} %"),
        ("Processed FPS", str(scorecard["fps_processed"])),
    ]
    lines = ["| Metric | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=None, help="scorecard JSON (a .md sibling is written too)")
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--tolerance", type=float, default=2.0, help="allowed drop in percentage points")
    args = parser.parse_args(argv)

    run = load_run(args.run)
    with open(args.labels, encoding="utf-8") as fh:
        labels = json.load(fh)
    summary_path = args.run.with_suffix(".summary.json")
    summary = json.loads(summary_path.read_text()) if summary_path.is_file() else None
    scorecard = evaluate(run, labels, summary)

    print(to_markdown(scorecard))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(scorecard, indent=2) + "\n", encoding="utf-8")
        args.out.with_suffix(".md").write_text(to_markdown(scorecard) + "\n", encoding="utf-8")
    if args.baseline:
        regressions = compare(scorecard, json.loads(args.baseline.read_text()), args.tolerance)
        if regressions:
            print("\nREGRESSION versus baseline:\n  " + "\n  ".join(regressions))
            return 1
        print("\nno regression versus baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
