# Project Chanakya v2

Project Chanakya is a self-hosted AI surveillance prototype. A Python backend (Flask, OpenCV,
YOLOv8, dlib) watches one or more cameras continuously, tracks people, vehicles, dogs and knives,
scores each track for threat, and records incidents with a snapshot and a short video clip. A React
dashboard shows the live feeds, the incident history, a zone editor and face enrollment. Alerts can
optionally be sent to a Telegram chat.

It is a student/research prototype, not a certified security product. Read
[Security and privacy](#security-and-privacy) and [Known limitations](#known-limitations) before
pointing it at real people or exposing it to a network.

## Contents

- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Setup](#setup)
- [Running](#running)
- [Demo mode with a video file](#demo-mode-with-a-video-file)
- [Configuration](#configuration)
- [HTTP API](#http-api)
- [How it works](#how-it-works)
- [Tests and CI](#tests-and-ci)
- [Security and privacy](#security-and-privacy)
- [Known limitations](#known-limitations)
- [What changed in v2](#what-changed-in-v2)

## Architecture

The detection engine is always on: it starts with the backend process and runs whether or not
anyone has the dashboard open. The web layer only reads what the engine produces.

```text
 camera source            webcam index | RTSP/HTTP URL | video file
        |
        v
+------------------+
|  ThreadedCamera  |      capture thread: keeps only the newest frame,
+------------------+      reconnects, stall watchdog, loops video files
        |
        v
+------------------+      one thread per camera, never shared between cameras
|   CameraWorker   |      resize 640x480 -> night vision -> pose (every 2nd frame)
+------------------+      -> YOLOv8n + ByteTrack -> per-track state:
        |                    zone at the feet, posture, speed anomaly, blink sampling,
        |                    face ID + emotion (every 5th frame)
        |                 -> ThreatAssessor: score 0-100, category, reasons
        |                 -> pre-roll buffer (VideoRecorder), annotated JPEG (latest-frame slot)
        v
+------------------+      shared by all workers, thread-safe
|   AlertManager   |      per-track dedup, cooldowns, escalation, weapon rules
+------------------+      -> snapshot JPEG -> SQLite row -> "incident" event -> Telegram (optional)
        |                 the worker then triggers the clip recording for that incident
        v
+------------------+      DatabaseManager: SQLite (WAL), one connection per call
|  DB + EventBus   |      EventBus: in-process pub/sub, never blocks a camera thread
+------------------+
        |
        v
+------------------+      performs no detection
|    Flask API     |      MJPEG  /video_feed/<id>   the worker's latest JPEG
|   (web/app.py)   |      REST   /api/*             incidents, stats, zones, faces, alerts, report
+------------------+      SSE    /api/events        EventBus subscription
        |
        v
+------------------+
| React dashboard  |      Vite dev server on :5173, or frontend/dist served by Flask on :5001
+------------------+
```

Objects created once per camera (never shared): `ThreadedCamera`, `YoloTracker`, `PoseEstimator`,
`TrackRegistry`, `AnomalyDetector`, `MovementPredictor`, `NightVision`, `VideoRecorder`.
ByteTrack keeps per-object identity state inside the YOLO model, so each camera needs its own model
instance.

Objects shared by all cameras (thread-safe): `DatabaseManager`, `EventBus`, `ZoneManager`,
`AlertManager`, `FaceRecognizer`, `EmotionDetector`, `ThreatAssessor`. Every call into dlib runs
under a single process-wide lock (`DLIB_LOCK`), because concurrent dlib calls from several threads
crash the process.

A housekeeping thread publishes a status event every 2 seconds while someone is subscribed, and
enforces retention at startup and every 6 hours.

## Repository layout

```text
surveillance-ai/
|-- README.md                     this file
|-- .github/workflows/ci.yml      backend pytest + frontend lint/build
|-- Backend/
|   |-- web/app.py                Flask app factory, auth, routes, entry point
|   |-- config/settings.py        constants and environment overrides
|   |-- src/
|   |   |-- engine/
|   |   |   |-- engine.py         SurveillanceEngine: builds, starts, stops everything
|   |   |   |-- worker.py         CameraWorker: the per-camera processing loop
|   |   |   |-- camera.py         ThreadedCamera
|   |   |   |-- detectors.py      YoloTracker, PoseEstimator
|   |   |   |-- posture.py        upright/prone from pose keypoints
|   |   |   |-- track_state.py    TrackState, TrackRegistry (identity vote, liveness status)
|   |   |   `-- alert_manager.py  AlertManager
|   |   |-- database_manager.py   SQLite incidents, stats, migration, purge
|   |   |-- zones.py              ZoneManager (normalised rectangles per camera)
|   |   |-- events.py             EventBus
|   |   |-- threat_assessor.py    threat scoring
|   |   |-- face_recognizer.py    face ID, enrollment, encodings cache
|   |   |-- liveness_detector.py  per-track blink tracking
|   |   |-- emotion_detector.py   landmark heuristic (experimental)
|   |   |-- anomaly_detector.py   running / erratic movement
|   |   |-- night_vision.py       low-light enhancement
|   |   |-- predictor.py          movement direction arrow
|   |   |-- video_recorder.py     pre/post-roll incident clips
|   |   |-- telegram_bot.py       Telegram notifier
|   |   |-- report_generator.py   PDF incident report
|   |   |-- security_vault.py     Fernet key handling, encrypt/decrypt
|   |   `-- audio_detector.py     experimental, NOT wired in (see Known limitations)
|   |-- tools/decrypt_report.py   decrypts a downloaded .pdf.enc report
|   |-- tests/                    pytest suite (no camera, no network, no model downloads)
|   |-- models/yolov8n.pt         detection weights
|   |-- yolov8n-pose.pt           pose weights
|   |-- requirements.txt          full runtime + test dependencies
|   |-- requirements-ci.txt       light set used by CI
|   |-- .env.example              environment template
|   `-- database/                 runtime data, git-ignored (created on first start)
`-- frontend/                     React 19 + Vite dashboard (plain CSS, lucide-react)
```

`Backend/sounds/alert.mp3` is a leftover asset that v2 does not use.

## Setup

Requirements:

- **Python 3.11.** The dlib and torch wheels are unreliable on 3.13 and later.
- **cmake** and a C++ compiler, needed to build dlib (pulled in by `face_recognition`).
  macOS: `brew install cmake`. Debian/Ubuntu: `sudo apt install cmake build-essential`.
- **Node.js 22** (the version CI uses; a current Node 20 also works with Vite).
- Optional: **ffmpeg** on the `PATH`. It is only used as a fallback to transcode incident clips to
  H.264 when OpenCV cannot write H.264 directly. Without it such clips stay in `mp4v`, which most
  browsers will not play inline (the download link still works).

Backend:

```bash
cd Backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optional; edit the values you need
```

Building dlib takes several minutes the first time. The model weights (`models/yolov8n.pt`,
`yolov8n-pose.pt`) are part of the repository.

Frontend:

```bash
cd frontend
npm ci
```

## Running

Backend (first terminal):

```bash
cd Backend
source venv/bin/activate
python web/app.py            # or: python -m web.app
```

The API listens on `http://127.0.0.1:5001`. At startup the engine loads and warms up one YOLO
tracker and one pose model per camera, opens the cameras, then starts the worker threads, so the
first frames appear a few seconds after launch. With the default configuration the backend opens
local cameras 0 and 1; a camera that cannot be opened is shown as OFFLINE and retried in the
background.

On macOS the terminal application needs camera permission (System Settings > Privacy & Security >
Camera). Grant it, then restart the backend.

Frontend in development (second terminal):

```bash
cd frontend
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. The dev build talks to `http://127.0.0.1:5001` unless `VITE_API_URL`
says otherwise.

Single-process alternative: build the dashboard once and let Flask serve it.

```bash
cd frontend
npm run build                # writes frontend/dist
cd ../Backend
python web/app.py            # now also serves the dashboard at http://127.0.0.1:5001/
```

The production build uses same-origin requests, so no CORS configuration is involved.

If `CHANAKYA_API_TOKEN` is set, the dashboard shows a login gate and asks for the token once; it is
kept in the browser's `localStorage`.

## Demo mode with a video file

No camera is needed. Point a camera id at a video file; the file is played at its native frame rate
and looped at the end, and the whole pipeline (tracking, scoring, incidents, clips) runs on it.

```bash
cd Backend
source venv/bin/activate
CHANAKYA_CAMERAS="demo=/absolute/path/to/clip.mp4" python web/app.py
```

Several sources can be mixed: `CHANAKYA_CAMERAS="alpha=0,demo=/absolute/path/to/clip.mp4"`.

A headless smoke run without the web server, printing status lines for ten seconds:

```bash
cd Backend
python -m src.engine.engine --source /absolute/path/to/clip.mp4 --seconds 10
```

## Configuration

Environment variables are read once, from the process environment and from `Backend/.env`
(`Backend/.env.example` documents each one). A malformed `CHANAKYA_CAMERAS` or `CHANAKYA_PORT` stops
the backend at startup with an error instead of silently falling back to the defaults. Error
messages never include a camera source, because sources can contain passwords.

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | unset | Bot token from @BotFather. Telegram alerts are disabled unless both Telegram variables are set. |
| `TELEGRAM_CHAT_ID` | unset | Numeric id of the chat that receives alerts. |
| `CHANAKYA_CAMERAS` | `alpha=0,bravo=1` | Comma-separated `id=source` pairs. `id`: `a-z 0-9 _ -`, 1-32 characters, unique, not `default`. `source`: digits = local camera index; `rtsp://`/`http://` URL (write a literal comma as `%2C`); or a video file path. The display name is the id in upper case. |
| `CHANAKYA_DATA_DIR` | `Backend/database` | Root of all runtime data: `chanakya.db`, `snapshots/`, `videos/`, `reports/`, `known_faces/`, `face_encodings.npz`, `zones.json`, `secret.key`. `~` is expanded; the path is made absolute. |
| `CHANAKYA_API_TOKEN` | unset (open mode) | Shared secret for the API, streams and downloads. Use at least 16 random characters. See [Authentication](#authentication). |
| `CHANAKYA_CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | Comma-separated browser origins allowed to call the API, and the only foreign origins allowed to send `POST`/`PUT`/`DELETE`. |
| `CHANAKYA_HOST` | `127.0.0.1` | Bind address. Anything other than `127.0.0.1`, `localhost` or `::1` requires `CHANAKYA_API_TOKEN`, otherwise the backend refuses to start (exit code 2). |
| `CHANAKYA_PORT` | `5001` | Bind port. |
| `CHANAKYA_DEBUG` | `false` | `1`/`true`/`yes`/`on` enables DEBUG-level logging. The Flask debugger and reloader are never enabled. |
| `VITE_API_URL` (frontend, build/dev time) | dev: `http://127.0.0.1:5001`; production build: same origin | Base URL of the backend as seen by the browser. |

Detection and alerting thresholds are constants in `Backend/config/settings.py`, not environment
variables. The ones most likely to need tuning:

| Constant | Default | Meaning |
|---|---|---|
| `CONFIDENCE_LIMIT` / `CLASS_CONFIDENCE` | `0.65` / `{43: 0.35}` | Minimum detection confidence; knives use a lower floor. |
| `HEAVY_EVERY_N_FRAMES` / `POSE_EVERY_N_FRAMES` | `5` / `2` | How often face ID + emotion, and pose, run per track / per frame. |
| `FACE_TOLERANCE` | `0.6` | Maximum face distance for a match (lower is stricter). |
| `EAR_THRESHOLD`, `LIVENESS_TTL`, `LIVENESS_GRACE`, `LIVENESS_MAX_VERIFY` | `0.22`, `30`, `15`, `45` s | Blink detection and liveness timing. |
| `LOITER_SECONDS`, `PRONE_MIN_SECONDS` | `10`, `1.5` s | Loitering and prone-posture durations. |
| `RUN_SPEED_BH`, `ERRATIC_SPEED_BH` | `2.0`, `1.2` | Speed thresholds in body-heights per second. |
| `ALERT_MIN_SCORE`, `ALERT_MIN_TRACK_AGE`, `ALERT_TRACK_COOLDOWN`, `ALERT_ESCALATION_DELTA` | `70`, `2` s, `60` s, `15` | When a track raises an incident, and when it may raise another. |
| `ALERT_CAMERA_MIN_INTERVAL`, `ALERT_NOTIFY_MIN_INTERVAL` | `3` s, `30` s | Per-camera spacing of incidents and of Telegram messages. |
| `WEAPON_MIN_HITS`, `WEAPON_ALERT_INTERVAL` | `4`, `10` s | Frames a knife must persist before alerting; spacing of weapon incidents. |
| `RETENTION_DAYS` | `30` | Age at which incidents, snapshots and clips are deleted. `0` disables retention. |
| `LOCAL_TZ` | `Asia/Kolkata` | Time zone used in PDF reports. Stored and API timestamps are always UTC. |

## HTTP API

All responses are JSON unless noted. Errors have the shape `{"error": "<message>"}`; a 500 always
returns exactly `{"error": "internal error"}` (details are logged server-side only). Timestamps are
UTC ISO-8601 with a `Z` suffix; the dashboard converts them to the viewer's locale. Request bodies
are limited to 6 MB.

### Authentication

- With `CHANAKYA_API_TOKEN` **set**, every route requires the token, sent as
  `Authorization: Bearer <token>` or as `?token=<token>`. The query form exists because `<img>`,
  `<video>`, `EventSource` and download links cannot send headers; it is redacted from the access
  log. Only `GET /api/health`, `GET /` and the static dashboard files are exempt, plus CORS
  preflight (`OPTIONS`) requests, which never carry credentials. The video feeds and report
  downloads are not exempt. A wrong or missing token returns `401 {"error":"unauthorized"}`.
- With the token **unset** (open mode), only requests whose `Host` header is `127.0.0.1`,
  `localhost` or `[::1]` are served; anything else returns `403 {"error":"forbidden host"}`. This
  blocks DNS-rebinding attacks against a local instance.
- In both modes, a `POST`/`PUT`/`DELETE` carrying an `Origin` header that is neither listed in
  `CHANAKYA_CORS_ORIGINS` nor the server's own origin returns `403 {"error":"forbidden origin"}`.

### Routes

| Method and path | Response |
|---|---|
| `GET /api/health` | `{"status":"ok","version","auth_required":bool,"uptime_s":int}`. Never requires the token. |
| `GET /api/cameras` | List of camera status objects: `{"id","name","online","fps","tracks","night_mode","last_frame_at","source","stream_url","snapshot_url"}`. `source` is a sanitised label (`camera:0`, a file name, or a URL without credentials and query string). |
| `GET /video_feed/<camera_id>` | MJPEG stream (`multipart/x-mixed-replace; boundary=frame`). 404 for an unknown id; at most 8 concurrent viewers per camera, then 503. An offline camera streams an "OFFLINE" placeholder. |
| `GET /video_feed_1`, `GET /video_feed_2` | Legacy aliases for the first and second configured camera (404 if absent). |
| `GET /api/cameras/<id>/snapshot.jpg` | Latest annotated frame as a JPEG, `Cache-Control: no-store`. `?raw=1` returns the clean 640x480 frame without overlays. |
| `GET /api/incidents` | `{"items":[...],"total","limit","offset"}`, newest first. Query: `limit` (1-200), `offset`, `min_threat`, `zone`, `camera`, `since` (ISO timestamp), `acknowledged=true\|false`. Invalid parameters return 400. |
| `GET /api/incidents/<id>` | One incident (see below). |
| `GET /api/incidents/<id>/snapshot` | `image/jpeg`. `?download=1` sends it as an attachment named `incident_<id>.jpg`. 404 unless the stored file lies inside the snapshots directory. |
| `GET /api/incidents/<id>/clip` | `video/mp4` with HTTP Range support. `?download=1` sends `incident_<id>.mp4`. 404 unless the stored file lies inside the videos directory. |
| `POST /api/incidents/<id>/ack` | Body `{"acknowledged": true\|false}` (no body means `true`). Returns the updated incident and publishes an `ack` event. |
| `GET /api/logs` | Legacy list of the 15 newest rows: `[{"timestamp","object","threat","zone"}]`. |
| `GET /api/stats?hours=24` | `hours` 1-168. `{"hours","total","critical","unacknowledged","by_hour":[{"hour","count"}],"by_zone":{},"by_camera":{}}`; `by_hour` has one zero-filled entry per hour, oldest first; `critical` counts scores of 70 and above. |
| `GET /api/zones` | `{"levels":["SAFE","PERIMETER","WARNING","CRITICAL"],"zones":{"default":[...],"<camera_id>":[...]}}`. |
| `PUT /api/zones/<camera_id>` | Body `{"zones":[{"name","level","rect":[x1,y1,x2,y2]}]}`. Returns `{"camera_id","zones":[...]}`. 404 unless the id is `default` or a configured camera; validation errors return 400. Publishes a `zones` event. |
| `GET /api/alerts` | `{"paused":bool}`. |
| `POST /api/alerts/pause`, `POST /api/alerts/resume` | `{"paused":bool}`. Pausing silences Telegram only; incidents are still recorded. |
| `GET /api/faces` | `{"people":[{"name","images"}]}`. |
| `POST /api/faces` | Multipart form with `name` and `image` (`.jpg`/`.jpeg`/`.png`, at most 5 MB). `201 {"name","images"}`; validation errors return 400. Publishes a `faces` event. |
| `DELETE /api/faces/<name>` | `{"removed":true}`, or 404 if nobody has that name. |
| `GET /api/modules` | Module status: emotion engine and classes, known-face count and names, per-camera stream state, whether Telegram is configured, recorder state. |
| `GET /api/events` | Server-Sent Events (see below). At most 32 concurrent subscribers, then 503. |
| `GET /api/report.pdf` | PDF incident report as a download. `?encrypted=1` returns the same report Fernet-encrypted as `<name>.pdf.enc` (`application/octet-stream`). |
| `GET /download_secure_report` | Legacy alias for the plain PDF report. |
| `GET /` | The built dashboard (`frontend/dist/index.html`) if it exists, otherwise `{"name":"Project Chanakya API","version"}`. |
| `GET /assets/<file>`, `GET /favicon.svg` | Static files of the built dashboard. There is no catch-all route. |

An incident as returned by the API:

```json
{
  "id": 42,
  "timestamp": "2026-09-22T14:03:11Z",
  "camera": "alpha",
  "object_type": "Person",
  "identity": null,
  "track_id": 7,
  "threat_score": 80,
  "category": "CRITICAL",
  "zone_level": "WARNING",
  "emotion": "Neutral",
  "reasons": ["In Warning Zone", "Unknown Identity"],
  "snapshot_url": "/api/incidents/42/snapshot",
  "clip_url": null,
  "acknowledged": false
}
```

File system paths are never exposed. `snapshot_url` and `clip_url` are `null` when the file does not
exist (yet) or lies outside its data directory. A clip is finalised a few seconds after the
incident; an `incident_updated` event announces it.

### Server-Sent Events

`GET /api/events` sends `event: <type>` / `data: <json>` pairs, starting with one `status` event,
and a `: ping` comment every 15 seconds.

| Event | Data |
|---|---|
| `status` | `{"cameras":[<camera status without URLs>],"alerts_paused":bool}` |
| `incident` | A new incident (API shape above). |
| `incident_updated` | The same incident after its clip was saved. |
| `ack` | `{"id","acknowledged"}` |
| `zones` | `{"camera_id"}` |
| `faces` | `{"count"}` |

A slow subscriber never blocks the engine: when its queue is full, its oldest event is dropped.

## How it works

### Threat scoring

`ThreatAssessor.calculate_threat` is a pure function of what is known about a track. A detected
weapon short-circuits to 100. Otherwise the score is the sum below, clamped to 0-100.

| Signal | Points |
|---|---|
| Zone: CRITICAL / WARNING / PERIMETER / SAFE | +40 / +30 / +20 / 0 |
| Object: person / car or motorcycle / dog | +30 / +40 / +10 |
| Person's face status: KNOWN / SPOOF / UNKNOWN / VERIFYING | -50 / +50 / +20 / 0 |
| Prone posture held for `PRONE_MIN_SECONDS` | +50 |
| Movement anomaly (RUNNING or ERRATIC) | +40 |
| Loitering: `LOITER_SECONDS` or more in a non-SAFE zone, and not KNOWN | +20 |

Categories: below 30 LOW, below 70 WARNING, otherwise CRITICAL. The reasons that contributed are
stored with the incident and shown in the dashboard.

Posture comes from pose keypoints (the torso angle between shoulders and hips), not from the shape
of the bounding box. Speed is measured in body-heights per second so that the verdict does not
depend on frame rate or on how far the person is from the camera.

### Identity and liveness

- Face recognition runs on the top 60% of a person's bounding box, in the full-resolution frame.
  The best match (smallest face distance within `FACE_TOLERANCE`) wins. Identity is a majority vote
  over the last five analyses in which a face was actually found, so a known person who turns away
  does not flip to "Unknown".
- Liveness is tracked **per track**. For a recognised person, the eye aspect ratio (EAR) is sampled
  on every frame at the last known face position, between the heavier face analyses. A blink is a
  short closed-eye run preceded and followed by open eyes; long closed runs are discarded as bad
  landmarks.
- Face status of a person track:
  - `UNKNOWN`: the face matches nobody (or no face has been found yet).
  - `KNOWN`: recognised, and a blink was seen within the last `LIVENESS_TTL` seconds. A continuous
    track that has been proven live once stays `KNOWN` while its face is merely out of view.
  - `SPOOF`: recognised, but the face was watched continuously for `LIVENESS_GRACE` seconds
    without a single blink.
  - `VERIFYING`: recognised and still waiting for a first blink. No alert is raised in this state.
    After `LIVENESS_MAX_VERIFY` seconds without a verdict the track falls back to `UNKNOWN`.
- Only `KNOWN` tracks are treated as authorised. Tracks that are not persons have status `N/A`.

### Incidents and alerts

A track raises an incident when its score is at least `ALERT_MIN_SCORE`, it is not authorised, it
has existed for `ALERT_MIN_TRACK_AGE` seconds, and it is not still `VERIFYING`. The same track
raises another incident only after `ALERT_TRACK_COOLDOWN` seconds or when its score rises by
`ALERT_ESCALATION_DELTA`. Non-weapon incidents on one camera are at least
`ALERT_CAMERA_MIN_INTERVAL` seconds apart. A knife must persist for `WEAPON_MIN_HITS` frames, skips
the age and verifying rules, and is limited to one incident per camera per `WEAPON_ALERT_INTERVAL`
seconds.

Each incident gets a snapshot (taken from the clean frame, with only that track's box drawn), a row
in SQLite, an `incident` event, and a video clip with about 5 seconds before and 5 seconds after the
trigger. Telegram receives at most one photo message per camera per `ALERT_NOTIFY_MIN_INTERVAL`
seconds, except for weapons and escalations, and nothing while alerts are paused.

### Zones

Zones are rectangles in normalised coordinates (0-1), so they are independent of the camera
resolution. Each camera can have its own set; cameras without one use the `default` set, which
ships as SAFE (left 40%), WARNING (middle) and CRITICAL (right 25%). Levels in ascending priority:
SAFE, PERIMETER, WARNING, CRITICAL. When zones overlap, the highest level wins; outside every zone
the level is SAFE.

A track's zone is evaluated at the **bottom centre of its bounding box**, that is, at the person's
feet, not at the centre of the body.

Edit zones in the dashboard's Zones tab (draw, move, resize, rename, set the level, save) or with
`PUT /api/zones/<camera_id>`. Saving an empty list for a camera resets it to the default set; the
default set itself cannot be emptied. Limits: at most 12 zones per set, names of 1-40 printable
characters, `0 <= x1 < x2 <= 1` and `0 <= y1 < y2 <= 1`. Zones are stored in
`<DATA_DIR>/zones.json` and take effect immediately.

### Face enrollment

Use the dashboard's Faces tab or `POST /api/faces`:

```bash
curl -H "Authorization: Bearer $CHANAKYA_API_TOKEN" \
     -F "name=Aryan Negi" -F "image=@/path/to/photo.jpg" \
     http://127.0.0.1:5001/api/faces
```

(Omit the header in open mode.) Rules:

- Name: starts with a letter, then letters, digits, spaces or hyphens, at most 40 characters. A name
  that differs from an existing one only in case is added to the existing person.
- Image: JPEG or PNG judged by content (not by file name), at most 5 MB and 25 megapixels, containing
  **exactly one** face.
- At most 10 images per person and 200 in total.

The upload is decoded with Pillow, rotated according to EXIF, scaled down to at most 1024 px and
re-encoded as a new JPEG, which removes EXIF and GPS metadata. It is stored as
`<DATA_DIR>/known_faces/<Name_With_Underscores>/<uuid>.jpg`, and the new encoding is active
immediately on all cameras.

Photos can also be copied in by hand, either as `known_faces/Aryan_Negi.jpg` or inside a folder
`known_faces/Aryan_Negi/`; underscores become spaces in the display name. The encodings cache
(`face_encodings.npz`, loaded without pickle) is rebuilt when the folder contents change; restart
the backend to pick up files added by hand. `DELETE /api/faces/<name>` deletes that person's image
files and encodings.

### Reports

`GET /api/report.pdf` builds a PDF of the most recent incidents (up to 500) with summary statistics.
Times are converted to `LOCAL_TZ` and the column is labelled with the zone abbreviation. The 20
newest reports are kept in `<DATA_DIR>/reports/`.

`GET /api/report.pdf?encrypted=1` returns the same report encrypted with Fernet (AES-128-CBC with
HMAC-SHA256). Encryption happens in memory; the plain PDF on disk is left intact and no `.enc` file
is written on the server. The key is created on first use at `<DATA_DIR>/secret.key` with file mode
0600 and is never overwritten. **Back this file up**: encrypted reports cannot be recovered without
it. To decrypt a download on a machine that has the key:

```bash
cd Backend
python tools/decrypt_report.py ~/Downloads/Chanakya_Report_20260922_140311_ab12cd.pdf.enc -o report.pdf
```

### Retention

At startup and every 6 hours, incidents older than `RETENTION_DAYS` are deleted together with their
snapshot and clip. The snapshots and videos directories are then swept for `*.jpg`/`*.mp4` files
older than the limit, so orphaned files do not outlive the policy. Enrolled faces are kept until
they are removed by hand or through the API.

### Migrating from v1

- The SQLite database is migrated in place on first start (new columns, UTC timestamps, best-effort
  camera ids). Back up `database/chanakya.db` first if the history matters.
- `database/face_encodings.pkl` is ignored and can be deleted; v2 never loads pickle files. The
  `known_faces/` photos are re-encoded into `face_encodings.npz` on first start.
- Install from `requirements.txt` (the old `requirement.txt` is gone).
- The stand-alone OpenCV window (`src/main.py`) and the Flask-rendered page (`web/templates/`) were
  removed. Use the React dashboard, or the headless smoke run shown under
  [Demo mode](#demo-mode-with-a-video-file).

## Tests and CI

Backend:

```bash
cd Backend
venv/bin/python -m pytest                 # fast suite; tests marked "slow" are deselected by pytest.ini
venv/bin/python -m pytest -m slow         # needs ultralytics / face_recognition and the model files
venv/bin/python -m pytest tests/test_zones.py -q
```

The tests use synthetic frames, fakes and temporary directories. They never open a camera, never
touch the network (Telegram is faked) and never download a model.

Lint, formatting, security scan and coverage (the same commands CI runs):

```bash
cd Backend
venv/bin/ruff check . && venv/bin/ruff format --check .
venv/bin/bandit -q -r config src web tools -x src/audio_detector.py
venv/bin/python -m pytest --cov=src --cov=web --cov=config --cov-fail-under=80
venv/bin/pip-audit --ignore-vuln PYSEC-2026-3447   # setuptools pin explained in requirements.txt
```

Install the tooling with `pip install -r requirements-dev.txt`. Dependabot
(`.github/dependabot.yml`) opens weekly update pull requests for pip, npm and the actions.

Accuracy is measured, not assumed: `Backend/eval/README.md` describes the replay harness that
runs a labeled clip through the real pipeline and compares the scorecard with
`Backend/eval/baselines/`. It runs as part of `pytest -m slow`.

Frontend:

```bash
cd frontend
npm run lint
npm run build
```

CI (`.github/workflows/ci.yml`) runs on pushes to `main` and on pull requests:

- **backend**: Ubuntu, Python 3.11, `pip install -r Backend/requirements-ci.txt`,
  `python -m pytest -m "not slow"` from `Backend/`. The CI requirement set deliberately leaves out
  ultralytics, torch, face_recognition (dlib) and lap and uses `opencv-python-headless`; every
  module that the fast tests import must therefore import without the heavy packages, which is
  why those packages are imported lazily in the code.
- **frontend**: Node 22, `npm ci`, `npm run lint`, `npm run build`.

## Security and privacy

1. **This repository's git history contains secrets and personal data.** Early commits include a
   real Telegram bot token in `.env` (the file was removed from the tree in commit `a955eed`, which
   does not remove it from history), face photos of a person, a pickled face-encodings file, the
   incident database, and snapshots and video clips of people under `database/`.
   - **Revoke the bot token now** with @BotFather (`/mybots` > the bot > API Token > Revoke current
     token) and put the new token only in `Backend/.env`.
   - Before the repository stays public, purge the history and force-push. Deleting the files in a
     later commit is not enough.

     ```bash
     pip install git-filter-repo
     git clone <your-remote-url> chanakya-purge
     cd chanakya-purge
     git filter-repo --invert-paths --path .env --path database
     git remote add origin <your-remote-url>      # filter-repo removes the remote on purpose
     git push --force --all origin
     git push --force --tags origin
     ```

     Every existing clone and fork still contains the old history; re-clone after the purge, and
     treat anything that was ever pushed as disclosed. That is why the token must be revoked and
     not merely removed.
   - `.env`, `database/`, `secret.key`, `*.key`, `*.enc`, `*.pkl`, `*.npz` and generated reports
     are now git-ignored.
2. **Data at rest is not encrypted, and people must be told.** Snapshots, clips, enrolled face
   photos and face encodings (biometric data) are stored unencrypted under `CHANAKYA_DATA_DIR`.
   Incidents, snapshots and clips are kept for `RETENTION_DAYS` (30 by default); enrolled faces are
   kept until they are removed. When Telegram is configured, alert photos are sent to Telegram, a
   third party outside your control. People who are enrolled or recorded must be informed, and
   recording needs a lawful basis (in India, notice and consent under the Digital Personal Data
   Protection Act, 2023). Protect the data directory with file permissions and disk encryption.
3. **Blink liveness does not stop a replayed video.** It defeats a printed photo or a still image
   on a screen. A video of an authorised person blinks, and will be accepted as live. Do not use
   face authorisation as the only control for anything that matters.
4. **Open mode is for loopback only.** Without `CHANAKYA_API_TOKEN` the API serves only requests
   addressed to `127.0.0.1`/`localhost`/`[::1]`, and the backend refuses to start on any other bind
   address. Set a token of at least 16 random characters before binding to a LAN address:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   The backend speaks plain HTTP using Flask's built-in server. On a network, the token and the
   video travel unencrypted unless a TLS-terminating reverse proxy or a VPN is put in front. There
   is one shared token: no user accounts, roles or audit trail.

Other measures in v2: path containment for every served file (`settings.safe_child`), an Origin
check on state-changing requests, a Host check in open mode, constant-time token comparison, the
token redacted from access logs, camera URLs (which may contain passwords) never logged or returned,
the Telegram token never logged, uploads decoded defensively with size and pixel limits, no pickle
loading, and generic 500 responses.

## Known limitations

- **Weapons:** the only weapon class is COCO "knife" from a nano-sized model. There is no firearm
  detection, small or partly hidden knives are missed, and knife-like objects cause false
  positives.
- **Emotion:** a heuristic over facial landmarks (eye opening, mouth opening and width, brow
  distance) with five classes, labelled experimental. It is not a trained classifier, it is
  unreliable on non-frontal faces, and it does not influence the threat score.
- **Small faces:** a face smaller than roughly 40 px in the frame cannot be recognised. With a
  typical webcam this means a few metres at most. Unrecognised people are treated as unknown.
- **`?token=` in URLs:** the query form of the token exists for media elements and SSE. It is
  redacted from the backend access log, but it can still end up in browser history or in the logs
  of a proxy placed in front of the backend.
- **Liveness:** see point 3 above. People who rarely blink or wear dark glasses may be classed as
  SPOOF after `LIVENESS_GRACE` seconds of continuous observation.
- **Posture and speed** are estimated from a single 2D view. A steep camera angle or a person
  lying along the camera axis gives "unknown" rather than "prone".
- **Zones** are axis-aligned rectangles evaluated at one point (the feet).
- **Performance:** inference runs on the CPU (about 18 FPS per camera with two cameras on the
  development Mac). GPU/MPS is deliberately not used from the worker threads.
- **Scale:** in-process threads, SQLite and the Flask development server. Suitable for a handful
  of cameras and viewers (at most 8 viewers per camera stream and 32 event subscribers), not for a
  production deployment.
- **Browsers** allow about six HTTP/1.1 connections per origin across all tabs. The dashboard
  therefore streams video only while the Dashboard tab is visible; several open dashboards in one
  browser still compete for connections.
- **Clips** may be `mp4v` instead of H.264 when neither OpenCV's H.264 writer nor ffmpeg is
  available; such clips download but do not play inline.
- **Audio:** `src/audio_detector.py` (YAMNet gunshot/scream detection) is experimental, is not
  wired into the engine, and its dependencies (TensorFlow Hub, PyAudio) are not in
  `requirements.txt`.

## What changed in v2

v1 was a demo whose detection loop lived inside the HTTP video response. v2 restructures it around
an always-on engine and fixes the following problems:

1. **Detection only ran while someone watched.** The pipeline ran inside the MJPEG response
   generator, so no viewer meant no detection and every extra browser tab started another full
   pipeline. Now one worker thread per camera runs continuously and viewers only read its latest
   JPEG.
2. **One YOLO tracker was shared by both cameras**, so ByteTrack identities collided. Each camera
   now has its own tracker and pose model, warmed up before any worker starts.
3. **Liveness was one global flag** that stayed true forever after anyone's first blink. It is now
   tracked per person track, expires, and distinguishes VERIFYING from SPOOF.
4. **Alerts spammed.** A 5-second cooldown per HTTP connection with no per-track memory flooded
   Telegram. The AlertManager now deduplicates per track, with cooldowns, escalation and a separate
   rate limit for notifications.
5. **The "secure report" could not be opened.** The PDF was Fernet-encrypted in place and still
   served as `.pdf`. The plain report is now a normal PDF; the encrypted variant is a separate
   `.pdf.enc` download with a decrypt tool.
6. **Face matching took the first match instead of the best**, "crawling" was a bounding-box aspect
   ratio, and the pose keypoints were computed but never used. Matching now takes the closest
   encoding, and posture comes from the keypoints.
7. **Night vision, the clip recorder, the anomaly detector and the zone manager existed but were
   only wired into a broken `src/main.py`.** They are now part of the engine, and zones are
   editable per camera instead of hard-coded.
8. **No authentication, `CORS(*)`, `debug=True`, UTC timestamps labelled IST, no tests, incomplete
   requirements.** v2 adds token authentication, an origin allow-list, loopback-only open mode,
   UTC storage with local display, a pytest suite with CI, and a complete `requirements.txt`.

Also new: incident snapshots and clips with acknowledge/filter/pagination, live updates over
Server-Sent Events, face enrollment from the dashboard, a retention policy, and sanitised camera
source labels. Removed: the stand-alone `src/main.py` loop and its helpers (`smart_alert.py`,
`tracker.py`, `camera_manager.py`, `shared_state.py`, `utils.py`), `test_telegram.py`, the
Flask-rendered `web/templates/`, and the partial `requirement.txt`.
