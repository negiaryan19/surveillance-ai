# Project Chanakya: roadmap to 10/10

Written 2026-09-22 against the v2 codebase (always-on engine, 483 tests, token auth).

## 1. Where the project stands

| Area | v1 | v2 (now) | 10/10 means |
|---|---|---|---|
| Architecture | 4 | 8 | Services that scale to N cameras on N nodes, restart-safe, observable |
| Detection reliability | 4 | 5.5 | Measured accuracy on your own footage, with targets that gate every release |
| Product / frontend | 6 | 8 | Operators can run a site from it for a month without asking for a feature |
| Code quality & tests | 5 | 8 | Coverage, contract, property and end-to-end tests; CI blocks regressions |
| Reproducibility & ops | 3 | 8 | One-command deploy, upgrades, backups, runbooks, 99.5 % uptime |
| Security | 2 | 7 | Users, roles, audit log, encrypted media, tested against an attacker |
| Privacy & legal | 1 | 5 | Consent, retention, erasure, DPIA, licences that allow your use |
| **Overall** | **5.5** | **~7.5** | **A system a stranger could deploy, trust, audit and maintain** |

The scores that hold the project back are the two you cannot fix by writing more
code: **nobody has measured whether it detects anything correctly**, and **nobody
has checked whether it may legally be used**. Everything below is ordered around
closing those two gaps first.

## 2. Evolve or rewrite?

"Change everything" is the right instinct for the *components*, not for the
*structure*. v2's structure (camera worker → track state → threat rules → alert
manager → event bus → API → SPA) is the one a rewrite would arrive at anyway,
and it is covered by 483 tests that encode hard-won behaviour (dlib crashes,
false-spoof alerts, clip callback binding, auth edge cases). Throwing that away
buys nothing.

What genuinely should be replaced, and why:

| Component | Now | Replace with | Why |
|---|---|---|---|
| Detector | YOLOv8n via Ultralytics | A larger model exported to ONNX / TensorRT / CoreML; **Apache-licensed** family (RT-DETR, YOLOX, D-FINE) unless you buy an Ultralytics licence | Ultralytics is AGPL-3.0: fine while the repo is public, a problem the day it is not. Nano is too weak for real scenes |
| Face pipeline | dlib / face_recognition (HOG + 128-d) | SCRFD detector + ArcFace-class embeddings in ONNX, trained or licensed for your use | dlib misses faces under ~80 px, is not thread-safe, and the accuracy gap to modern models is large. Note: InsightFace's pretrained weights are non-commercial |
| Liveness | Blink (EAR) only | Blink **and** a passive anti-spoof model (MiniFASNet-class) | Blink cannot stop a replayed video; both together can |
| Tracker | ByteTrack | BoT-SORT with ReID embeddings | Stable ids through occlusion; cross-camera identity |
| Emotion | Landmark heuristic | Remove, or a trained FER model behind an "experimental" flag | It is a demo feature with invented confidences |
| Video transport | MJPEG over HTTP/1.1 | WebRTC (go2rtc / mediamtx) or LL-HLS | MJPEG costs one connection per viewer and ~10× the bandwidth of H.264 |
| Recording | 10 s incident clips | Continuous ring recording (segments) with incident bookmarks | Investigations need "what happened before and after" |
| API server | Flask dev server | FastAPI + uvicorn (async SSE/WebSocket, OpenAPI, pydantic) or Flask behind gunicorn/gevent | The dev server is single-process and unsupported for production |
| Storage | SQLite + local files | Postgres + object storage (MinIO/S3) once there is more than one node | Multi-node, backups, concurrent writers |
| Auth | One shared token | Users, roles, sessions/OIDC, MFA, API keys | A shared secret cannot be revoked per person or audited |
| Frontend | React 19, JavaScript | TypeScript, TanStack Query, component + e2e tests | Type errors are the frontend's main bug class; contracts should be checked |

Keep: the engine/worker structure, track state machine, alert rules, zone model,
event bus, database migration path, the test suite, the security decisions in the
API (they transfer to any framework), the README's security section.

## 3. Definition of done for 10/10

Every item is measurable. A phase is not finished until its exit criteria pass
in CI or in a signed-off test run.

| Dimension | Target |
|---|---|
| Person detection | Recall ≥ 0.95 and ≤ 0.1 false positives / minute / camera on the validation set |
| Identity | True accept rate ≥ 0.95 at false accept rate ≤ 0.1 % on enrolled people |
| Spoof resistance | ≥ 0.90 detection of photo, screen and video replay at ≤ 2 % false spoof rate |
| Alerting | ≤ 1 false alert / hour / camera; alert latency p95 < 2 s from event to notification |
| Throughput | 8 × 1080p cameras at ≥ 12 FPS each on one GPU host, or 2 cameras per edge device |
| Availability | ≥ 99.5 % over 30 days; recovers from camera, DB and network loss without operator action |
| Security | Users/roles/MFA, TLS, audit log, media encrypted at rest, secrets in a manager, no high findings from SAST + dependency scan + a pen test |
| Privacy | Consent record for every enrolled person, retention enforced per data class, erasure request handled end to end, DPIA written, notices/signage produced |
| Product | 5 operators complete the core tasks unaided with ≥ 90 % success; SUS ≥ 80 |
| Engineering | ≥ 85 % line coverage, mutation score ≥ 70 % on core rules, contract tests from OpenAPI, e2e tests on the SPA, model-evaluation gate in CI |
| Operations | One-command install/upgrade/backup/restore; runbook for every alert; Grafana dashboards |
| Validation | One real site, 30 days, operator feedback incorporated |

## 4. Phases

Effort estimates assume one experienced engineer full-time. Three people can run
phases 2, 3 and 4 in parallel after phase 1.

### Phase 0: ship v2 and close the leak (1 week)

- Revoke the Telegram token in @BotFather; purge `.env` and `database/` from git
  history (`git filter-repo`), force-push, tell anyone who cloned.
- Commit v2, tag `v2.0.0`, make CI green on GitHub.
- Deploy on one LAN machine behind `CHANAKYA_API_TOKEN` with the two real cameras.
- Start collecting evaluation footage **with consent**: 30–60 minutes/day, both
  cameras, covering day, dusk, night, rain, crowds, and staged events (a stranger
  walking in, a known person, a photo held up, a phone video replay, someone
  crouching/falling, a knife, a phone that looks like a knife).

Exit: 14 days of continuous running; ≥ 10 hours of consented footage; a list of
every false and missed alert the operator noticed.

### Phase 1: measure before changing anything (2 weeks)

Nothing in phases 2–7 can be judged without this.

- Label the footage: person boxes + identity + event tags (CVAT or Label Studio).
  Target ≥ 2 hours labeled, ≥ 200 events.
- `tools/replay.py`: run any clip through the real engine with an injected clock at
  maximum speed, deterministic seeds, and dump every detection, track state
  transition and alert to JSONL.
- `tools/evaluate.py`: precision/recall for detection, identity accuracy,
  spoof/live confusion matrix, alert precision/recall, latency, FPS. Emits a
  scorecard (Markdown + JSON).
- Baseline scorecard committed under `eval/baselines/v2.0.0.json`.
- CI job: replay a 5-minute fixture and fail if any metric regresses > 2 points.
- Fix the cheap things the baseline exposes (thresholds, zone geometry,
  cooldowns). Do not touch models yet.

Exit: baseline scorecard; regression gate in CI; every later phase reports
against it.

Status 2026-09-22: the harness exists (`Backend/tools/{make_fixture,replay,evaluate}.py`,
`Backend/eval/README.md`) with a synthetic labeled fixture and baseline
`eval/baselines/v2.0.0.json` (detection P 94.7 % / R 77.9 %, 3/3 intrusions,
0 false alerts). The regression gate runs as a `slow` test. Still missing: real,
consented footage from the deployment cameras and its labels.

### Phase 2: perception that earns the claims (4–6 weeks)

- **Detector.** Evaluate three candidates on the Phase-1 set at 640 and 960 input:
  a mid-size YOLO (licence permitting), RT-DETR-R18/R50, D-FINE. Export the winner
  to ONNX; TensorRT on NVIDIA, CoreML on Apple, OpenVINO on Intel. Trim classes to
  what the threat model uses (person, vehicle types, animal). Per-class thresholds
  from the ROC curves, not guesses.
- **Weapons.** Either train a dedicated detector on a weapons dataset (guns and
  knives, ≥ 5 000 labeled frames incl. hard negatives: phones, pens, tools) and
  require ≥ 0.9 precision at the chosen threshold, or remove the feature and the
  claim. There is no middle ground that is honest.
- **Faces.** SCRFD (or equivalent) detector + a 512-d embedding model with a
  licence that covers your use. Enrollment: 3–5 angles, quality gate (blur, size,
  pose), duplicate check. Matching by cosine distance with a threshold set from
  the eval set. Thread-safe runtime (ONNX Runtime sessions per worker) so the
  global lock can go.
- **Liveness.** Passive anti-spoof model on the face crop every N frames, fused
  with the existing blink state machine; KNOWN requires both. Evaluate against
  printed photo, phone screen, laptop screen, video replay.
- **Tracking and re-identification.** BoT-SORT with an OSNet-class ReID model;
  persist embeddings per track so a person who leaves and returns, or crosses to
  the other camera, keeps one identity.
- **Behaviour.** Replace single-frame posture with a temporal model over pose
  sequences (fall, crawl, run, loiter, fight) trained on public datasets plus your
  staged events; per-camera anomaly baselines (typical speed and dwell per zone).
- **Emotion.** Remove from scoring. Keep only if a trained FER model beats 70 %
  on FER+ and it is labeled experimental in the UI.
- **Scene.** Replace mean-brightness night mode with per-camera exposure
  statistics; add camera tamper/blur/occlusion detection.

Exit: detection, identity, spoof and alert targets from section 3 met on the
Phase-1 set; scorecard diff committed with the release.

### Phase 3: platform (4–6 weeks)

- **Process model.** `engine` becomes a standalone process per node (one worker
  per camera, model sessions shared per process); `api` is stateless; they talk
  over Redis Streams (or NATS). The event bus becomes Redis pub/sub so several API
  replicas and several engine nodes see the same events.
- **API.** FastAPI + uvicorn, pydantic models generated from the current JSON
  shapes, OpenAPI published, SSE and WebSocket endpoints, background tasks for
  reports. Keep every security rule from v2 (they are framework-independent).
- **Storage.** Postgres with Alembic migrations (the v2 migration becomes the
  first revision); media in object storage with signed, expiring URLs; Redis for
  rate limits and dedup state so alert rules survive restarts.
- **Video.** RTSP/ONVIF ingest with hardware decode (GStreamer or FFmpeg);
  continuous ring recording as 10-second H.264 segments with a retention budget;
  incidents become bookmarks into the ring; live viewing via WebRTC through
  go2rtc/mediamtx; MJPEG kept only as a fallback.
- **Packaging.** Docker Compose for single-host (api, engine, db, redis, media,
  reverse proxy with TLS); Helm chart for Kubernetes; GPU and CPU variants; config
  as validated YAML + env; `chanakya` CLI for install, upgrade, backup, restore,
  doctor.
- **Observability.** Prometheus metrics (per-camera FPS, inference latency, queue
  depth, alert counts, dropped frames), structured JSON logs with request ids,
  OpenTelemetry traces across api→engine, Grafana dashboards, alert rules for
  camera down / FPS collapse / disk nearly full.
- **Resilience.** Health and readiness endpoints; watchdog restarts; graceful
  drain; idempotent alert delivery with retries and a dead-letter queue.

Exit: 8 cameras at target FPS on one host; a 30-day staging soak at ≥ 99.5 %;
install from zero in under 15 minutes by someone who did not build it.

### Phase 4: security and privacy (3–4 weeks, can overlap phase 3)

- **Identity and access.** User accounts, roles (admin, operator, viewer,
  auditor), sessions with rotation, MFA (TOTP), optional OIDC (Keycloak/Authentik),
  scoped API keys for integrations, per-route rate limits, CSRF tokens for
  cookie sessions, TLS terminated by Caddy/Traefik with HSTS.
- **Data protection.** Media and embeddings encrypted at rest with keys held by a
  KMS or age/sops; per-object access logged; secrets never in env files on disk
  in production.
- **Audit.** Append-only audit log (who viewed which incident/clip, enrolled or
  removed whom, changed zones or thresholds, exported what), exportable and
  tamper-evident (hash chain).
- **Privacy programme.** Consent registry for enrolled people with proof of
  notice; auto-generated signage and privacy notice; data-subject access and
  erasure workflow that removes embeddings, photos, snapshots and clips of one
  person; face blurring of non-enrolled people in exports; retention per data
  class (live ring, incident media, embeddings, logs); a written DPIA mapped to
  the DPDP Act and, if relevant, GDPR.
- **Assurance.** SAST (bandit, semgrep), dependency scanning (pip-audit, npm
  audit, Dependabot), container scanning (trivy), SBOM per release, fuzzing of
  uploads and JSON endpoints (hypothesis, schemathesis), a written STRIDE threat
  model, and one external penetration test with findings closed.

Exit: pen-test report with no high findings; DPIA signed by the owner; erasure
request completed end to end in a test.

### Phase 5: product and UX (4–6 weeks)

- **Frontend engineering.** TypeScript migration; TanStack Query for server
  state; generated API client from OpenAPI; Vitest + Testing Library for
  components; Playwright end-to-end suite against a seeded backend; Storybook;
  axe accessibility checks in CI; design tokens documented.
- **Operator features.** Camera wall with drag layout; site map/floorplan with
  camera positions and zone overlays; timeline scrubber over the continuous
  recording with incident markers; incident search, tags, notes, assignment;
  person view (every sighting of one identity); alert routing (Telegram, email,
  SMS, Web Push, webhooks, PagerDuty) with schedules and escalation; exports with
  redaction; scheduled reports; threshold and rule settings with preview against
  recent footage; onboarding wizard with ONVIF discovery; English and Hindi.
- **Mobile.** PWA with push notifications first; native app only if the PWA
  proves insufficient.

Exit: usability study with five operators, task success ≥ 90 %, SUS ≥ 80;
Playwright suite covers every operator task.

### Phase 6: scale, edge and resilience (3–4 weeks)

- Edge build for Jetson (TensorRT) and Raspberry Pi 5 + Hailo (HailoRT) running
  the engine per site with local ring recording; central server aggregates
  events and media on demand; offline buffering and sync; signed OTA updates.
- Multi-site tenancy in the data model and UI; backups verified by automated
  restore; chaos tests (kill a camera, the DB, the network) with runbooks for
  each; load tests (k6) for API and streams; 72-hour soak on target hardware.

Exit: one real site for 30 days meeting the availability and alert targets.

### Phase 7: quality bar, governance, release (2 weeks setup, then ongoing)

- Coverage ≥ 85 %; mutation testing on threat rules, alert manager, zones,
  liveness; property-based tests for geometry and rules; contract tests generated
  from OpenAPI; model cards and dataset cards; architecture decision records;
  CHANGELOG, semantic versioning, signed release artefacts, SBOM.
- Docs site (MkDocs): architecture, operations runbook, API reference, model
  evaluation methodology, privacy documentation, contributor guide.
- Licence review: every model and library, with a table in the docs; replace
  anything that does not permit your intended use.

Exit: `v3.0.0` released with the section-3 scorecard published.

Status 2026-09-22: ruff (lint + format), bandit, pip-audit and a coverage floor
of 80 % are wired into CI; coverage is 90 %; Dependabot is configured. The
`setuptools<81` pin is a documented accepted risk until the dlib stack is
replaced (phase 2).

## 5. Sequencing and timeline

```
Week   1     Phase 0  ship v2, rotate token, deploy, collect footage
Week   2-3   Phase 1  evaluation harness + baseline (blocks everything else)
Week   4-9   Phase 2  perception            ┐
Week   4-9   Phase 3  platform              ├ parallel with 2-3 people
Week   7-10  Phase 4  security & privacy    ┘
Week  10-15  Phase 5  product & UX
Week  15-18  Phase 6  scale, edge, 30-day site run
Week  18-20  Phase 7  quality bar, docs, v3.0.0
```

Solo and full-time: roughly six to seven months. The 30-day site run in phase 6
is calendar time you cannot compress.

## 6. If you have four weeks, not six months

Do phases 0 and 1 in full, then only these from phase 2 and 4:

1. Replace dlib with an ONNX face detector + embedding model and measure the gain.
2. Add passive anti-spoofing next to blink.
3. Swap the detector for a mid-size ONNX model and re-tune thresholds from ROC
   curves.
4. Users and roles with sessions and MFA; encrypted media at rest.
5. Continuous ring recording (even without WebRTC).

That gets detection reliability and security to ~8 each and the overall to
about 8.5. Everything else is what separates 8.5 from 10.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Model licences (AGPL detector, non-commercial face weights) block deployment | Decide the intended use now; choose Apache/MIT models or budget for licences in phase 2 |
| No consent for evaluation footage | Written consent and signage before phase 0 recording; stage events with volunteers |
| GPU cost | Benchmark CPU-only ONNX on the real host first; edge accelerators (Hailo) are cheap per camera |
| Feature creep in phase 5 | Every feature must trace to an operator task from the usability study |
| Regressions during the rewrite of components | The phase-1 gate runs on every pull request; no merge below baseline |
