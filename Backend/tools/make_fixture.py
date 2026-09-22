"""Build the labeled evaluation fixture from the two sample photos that ship with ultralytics.

The clip pans a 640x480 window over ``bus.jpg`` and ``zidane.jpg``; because the
person boxes on the still photos were verified by hand, every frame's ground
truth is a pure geometric transform of those boxes. That makes the fixture
reproducible from the repository alone (no video is committed) and independent
of any detector.

Usage:
    python -m tools.make_fixture --out-dir eval/fixtures        # writes pan_demo.mp4 + pan_demo.labels.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

FPS, W, H = 15, 640, 480
NAME = "pan_demo"

# Person boxes on the ORIGINAL photos, verified visually (x1, y1, x2, y2).
# ``ignore`` marks a person cut off by the photo edge: never a miss, never a false positive.
SOURCES = {
    "bus.jpg": {
        "people": [
            {"label_id": "bus-fur-coat", "bbox": (48, 398, 245, 902)},
            {"label_id": "bus-black-coat", "bbox": (221, 405, 345, 857)},
            {"label_id": "bus-right-edge", "bbox": (669, 392, 809, 877)},
            {"label_id": "bus-left-sliver", "bbox": (0, 560, 40, 870), "ignore": True},
        ],
    },
    "zidane.jpg": {
        "people": [
            {"label_id": "zidane", "bbox": (114, 197, 1114, 711)},
            {"label_id": "ancelotti", "bbox": (748, 41, 1142, 713)},
        ],
    },
}


PAN_ROOM = 200  # every photo is scaled so the window can slide at least this far
MIN_VISIBLE = 0.5  # a person must be at least half inside the frame before a miss counts against the detector


def source_scale(shape) -> float:
    """Scale so the photo is at least W + PAN_ROOM wide and at least H tall (never stretched)."""
    h, w = shape[:2]
    return max((W + PAN_ROOM) / w, H / h)


def band_origin(people, scale: float, bh: int) -> int:
    """Vertical window origin that centres the labelled people (clamped to the photo)."""
    ys = [v * scale for person in people if not person.get("ignore") for v in (person["bbox"][1], person["bbox"][3])]
    centre = (min(ys) + max(ys)) / 2 if ys else bh / 2
    return int(max(0, min(bh - H, centre - H / 2)))


# The pan schedule: (photo, seconds, start fraction, end fraction of the pan range).
SCHEDULE = [
    ("bus.jpg", 4, 0.0, 1.0),
    ("bus.jpg", 3, 1.0, 0.0),
    ("zidane.jpg", 3, 0.0, 1.0),
    ("zidane.jpg", 2, 1.0, 0.5),
]


def default_zone(nx: float) -> str:
    """The default zone set: left 40 % SAFE, middle WARNING, right 25 % CRITICAL."""
    if nx >= 0.75:
        return "CRITICAL"
    if nx >= 0.4:
        return "WARNING"
    return "SAFE"


def build(out_dir: Path, assets: Path) -> tuple[Path, Path]:
    import cv2
    import numpy as np

    from config import settings

    images = {name: cv2.imread(str(assets / name)) for name in SOURCES}
    for name, img in images.items():
        if img is None:
            raise SystemExit(f"missing sample photo {assets / name}")
    out_dir.mkdir(parents=True, exist_ok=True)
    clip = out_dir / f"{NAME}.mp4"
    writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    frames: dict[str, list[dict]] = {}
    feet_zone: dict[str, list[tuple[int, str]]] = {}
    frame_index = 0
    for name, seconds, start_frac, end_frac in SCHEDULE:
        scale = source_scale(images[name].shape)
        big = cv2.resize(images[name], None, fx=scale, fy=scale)
        bh, bw = big.shape[:2]
        y0 = band_origin(SOURCES[name]["people"], scale, bh)
        pan = bw - W
        n = int(seconds * FPS)
        for i in range(n):
            frac = start_frac + (end_frac - start_frac) * i / max(n - 1, 1)
            x0 = int(max(0, min(pan, pan * frac)))
            frame = big[y0 : y0 + H, x0 : x0 + W]
            if frame.shape[:2] != (H, W):  # would desynchronise the labels from the pixels
                raise SystemExit(f"window {frame.shape[:2]} != {(H, W)} for {name}; check source_scale")
            writer.write(np.ascontiguousarray(frame))
            labels = []
            for person in SOURCES[name]["people"]:
                sx1, sy1, sx2, sy2 = (v * scale for v in person["bbox"])
                x1, y1, x2, y2 = sx1 - x0, sy1 - y0, sx2 - x0, sy2 - y0
                cx1, cy1, cx2, cy2 = max(0, x1), max(0, y1), min(W, x2), min(H, y2)
                if cx2 - cx1 <= 0 or cy2 - cy1 <= 0:
                    continue
                visible = ((cx2 - cx1) * (cy2 - cy1)) / max(1.0, (x2 - x1) * (y2 - y1))
                if visible < 0.15:
                    continue
                entry = {
                    "label_id": person["label_id"],
                    "class": "Person",
                    "bbox": [int(cx1), int(cy1), int(cx2), int(cy2)],
                }
                if person.get("ignore") or visible < MIN_VISIBLE:
                    entry["ignore"] = True  # too little of the body visible to demand a detection
                labels.append(entry)
                if not entry.get("ignore"):
                    feet_zone.setdefault(person["label_id"], []).append(
                        (frame_index, default_zone((cx1 + cx2) / 2 / W))
                    )
            frames[str(frame_index)] = labels
            frame_index += 1
    writer.release()

    # Expected alerts: an unknown person whose feet stay outside SAFE for at least
    # ALERT_MIN_TRACK_AGE seconds should produce one incident in that window.
    min_frames = int(settings.ALERT_MIN_TRACK_AGE * FPS)
    events = []
    for label_id, seq in feet_zone.items():
        run_start = None
        prev_frame = None
        for frame, zone in seq + [(None, "SAFE")]:
            contiguous = prev_frame is not None and frame is not None and frame == prev_frame + 1
            if zone != "SAFE" and (run_start is None or not contiguous):
                if run_start is not None and prev_frame - run_start + 1 >= min_frames:
                    events.append(
                        {"type": "intrusion", "label_id": label_id, "zone": None, "start": run_start, "end": prev_frame}
                    )
                run_start = frame
            elif zone == "SAFE" and run_start is not None:
                if prev_frame - run_start + 1 >= min_frames:
                    events.append(
                        {"type": "intrusion", "label_id": label_id, "zone": None, "start": run_start, "end": prev_frame}
                    )
                run_start = None
            prev_frame = frame
    labels_path = out_dir / f"{NAME}.labels.json"
    labels_path.write_text(
        json.dumps(
            {
                "fps": FPS,
                "width": W,
                "height": H,
                "frames": frames,
                "events": events,
                "event_tolerance_frames": 2 * FPS,
                "source": "ultralytics sample photos bus.jpg and zidane.jpg, boxes verified by hand",
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return clip, labels_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=_BACKEND / "eval" / "fixtures")
    parser.add_argument("--assets", type=Path, default=None, help="folder with bus.jpg and zidane.jpg")
    args = parser.parse_args(argv)
    assets = args.assets or Path(importlib.import_module("ultralytics").__file__).parent / "assets"
    clip, labels = build(args.out_dir, assets)
    data = json.loads(labels.read_text())
    print(f"clip: {clip}\nlabels: {labels}\nframes: {len(data['frames'])}  events: {len(data['events'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
