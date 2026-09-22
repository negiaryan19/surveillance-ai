# Evaluation harness

Measures what the pipeline actually does on labeled footage, so model and
threshold changes are judged by numbers rather than by watching the stream.

## Pieces

| Tool | Purpose |
|---|---|
| `tools/make_fixture.py` | Builds `fixtures/pan_demo.mp4` (12 s, 640x480, 15 fps) by panning over the two sample photos that ship with ultralytics, and writes `fixtures/pan_demo.labels.json` from hand-verified person boxes. The clip is regenerated, not committed. |
| `tools/replay.py` | Runs a clip through the real `CameraWorker` (real YOLO, pose, dlib) with an injected clock, so results are deterministic. Writes one JSON line per frame with every track and incident. Telegram is never called. `--conf` overrides the detector floor for threshold sweeps. |
| `tools/evaluate.py` | Scores a replay against labels: per-frame person detection P/R/F1 at IoU 0.5, identity switches, alert recall/precision against expected intrusion events, processed FPS. `--baseline` makes it exit 1 on a regression. |
| `baselines/<version>.json` | The scorecard the current release must not regress from. |

```bash
cd Backend
venv/bin/python -m tools.make_fixture --out-dir eval/fixtures
venv/bin/python -m tools.replay --clip eval/fixtures/pan_demo.mp4 --out /tmp/run.jsonl
venv/bin/python -m tools.evaluate --run /tmp/run.jsonl --labels eval/fixtures/pan_demo.labels.json \
    --baseline eval/baselines/v2.0.0.json
```

The same flow runs as `tests/test_eval_harness.py::test_fixture_replay_matches_baseline`
(`pytest -m slow`), so a pull request that lowers a headline metric by more than 3 points fails.

## Label format

```json
{
  "fps": 15,
  "frames": {"0": [{"label_id": "bus-fur-coat", "class": "Person", "bbox": [32, 145, 163, 480]}]},
  "events": [{"type": "intrusion", "label_id": "zidane", "zone": null, "start": 105, "end": 146}],
  "event_tolerance_frames": 30
}
```

* A label with `"ignore": true` (a person less than half inside the frame) is never a miss and
  never turns an overlapping detection into a false positive.
* An event is hit when any incident is logged inside `[start - tol, end + tol]`; `zone: null`
  accepts any zone. One incident may satisfy several overlapping events: one alert for a group
  entering together is the intended behaviour, not a miss.

## Baseline v2.0.0 (yolov8n, default settings, this fixture)

| Metric | Value |
|---|---|
| Detection precision | 94.7 % |
| Detection recall | 77.9 % |
| Identity switches | 3 |
| Expected events hit | 3 / 3 |
| False alerts | 0 |
| Processed FPS (M-series CPU) | ~15 |

Where recall is lost: a person bent over with an arm across a neighbour (the detector boxes
only the torso, IoU < 0.5) and people cut off by the frame edge. Both are real detector
limitations that a stronger model (ROADMAP.md phase 2) is expected to fix.

Confidence-floor sweep on the same fixture (evidence for phase 2, not yet applied to the
default of 0.65 because the fixture has no clutter that would produce false positives):

| Floor | Precision | Recall | False alerts |
|---|---|---|---|
| 0.65 (default) | 94.7 % | 77.9 % | 0 |
| 0.50 | 90.1 % | 84.2 % | 0 |
| 0.40 | 89.2 % | 87.5 % | 0 |

## Adding real footage

1. Record with consent (see the README's privacy section) and copy the clip somewhere outside
   the repository.
2. Label person boxes per frame (CVAT or Label Studio export, converted to the format above)
   and list the intrusion events you expect alerts for.
3. Replay and evaluate as above; commit the scorecard under `baselines/` when it becomes the
   new floor.
