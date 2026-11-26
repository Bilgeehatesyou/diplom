# AI Proctor — Diploma Project Context

**Owner:** Г.Билгээ (B22FA1260), СЭЗИС МСМ 2026
**Status:** Diplom III defense-ready (2026-05-15)

## What this is

Real-time online exam proctoring system. Student takes an exam in browser → backend
analyzes video (face, gaze, multiple faces, forbidden objects) and audio (speech, whispering,
talking) → teacher dashboard shows live video + flagged events. Built for СЭЗИС.

## Stack

- **Backend:** FastAPI + WebSocket (Python 3.11), SQLite (`aiproctor.db`)
- **AI:** MediaPipe (face/gaze), YOLOv8 (objects), Silero VAD (speech), WavLM classifier (audio cheating)
- **Frontend:** Next.js 14, two separate apps:
  - `apps/student` (port 3000) — exam-taking UI
  - `apps/teacher` (port 3001) — monitoring dashboard
- **ffmpeg:** required for WebM→PCM audio decoding (pydub). Auto-detected on Win/macOS/Linux.

## Auth (seeded on first DB init)

| Role | ID | Password |
|---|---|---|
| Student | `B22FA1260` (Г.Билгээ) | `123456` |
| Teacher | `Tsetsegee` | `123456` |

Passwords are bcrypt-hashed (old plaintext rows auto-migrated on startup). Login returns a JWT (HS256,
`SECRET_KEY` from `backend/.env`); every teacher REST endpoint requires role=teacher, exam endpoints role=student.
WebSockets authenticate with a first message `{"type":"auth","token":...}` (not in URL → not in access logs);
student_id comes from the token, never from the URL.

## Running

```bash
# Terminal 1 — Backend
cd backend && source .venv/bin/activate && python -m uvicorn main:app --reload

# Terminal 2 — Student
cd apps/student && npm run dev

# Terminal 3 — Teacher
cd apps/teacher && PORT=3001 npm run dev
```

Setup (first time on a new machine):
- macOS: `brew install python@3.11 node ffmpeg`
- Windows: install Python 3.11, Node.js, `winget install ffmpeg`
- Then: `python3.11 -m venv .venv && pip install -r backend/requirements.txt`
- Then: `npm install` in both `apps/student` and `apps/teacher`
- **Manually transfer** `models/cheating_classifier_v2/` (~500MB, gitignored) — needed for audio classifier

## Architecture (must-know files)

- `backend/api/websocket.py` — student & teacher WS (token auth), per-student video/audio workers + watchdog, teacher frame queues, background loop (decay, expired-session close, score push)
- `backend/api/routes.py` — REST: login (JWT), `/api/exam/start|answers|submit` (student), `/api/dashboard`, `/api/session/{id}/submission`, history, CSV, `/api/incident/...` (all teacher-only)
- `backend/auth.py` — JWT issue/verify, bcrypt, `require_student` / `require_teacher` deps
- `backend/exam_service.py` — session lifecycle rules (start/resume, finalize, retake policy, server-side deadline)
- `backend/exams.py` — exam definition (questions, duration) served to the client
- `backend/ai/analyzer.py` — `analyze_frame` (MediaPipe + YOLO) and `analyze_audio_samples` (VAD + classifier + RMS heuristics)
- `backend/db.py` — SQLAlchemy models: Student, Teacher, ExamSession (partial unique index: one active per student+exam), RiskEvent (`session_id` FK), Submission; idempotent SQLite migration in `_migrate`
- `backend/utils/log.py` — colored terminal logging (VAD speech/silence visually distinct)
- `apps/student/app/exam/page.tsx` — exam UI: questions/timer from server, autosave, 5 fps 640px frames + 2s WebM audio, fullscreen/focus/copy/virtual-camera reporting
- `apps/teacher/app/page.tsx` — dashboard, binary frame streaming, server-pushed scores, answers modal; `components/AuthImage.tsx` loads snapshots with the token
- `apps/*/lib/api.ts` — token storage + authenticated fetch

## Detection events (severity → risk score)

| Event | Severity | Trigger |
|---|---|---|
| `face_missing` | high (15pts) | No face for 5+ seconds |
| `multiple_faces` | high | >1 face in frame |
| `gaze_away` | medium (7pts) | Calibrated head pose (solvePnP): yaw >25° / up >20° / iris >0.18 from the student's own baseline, 3+ s |
| `looking_down` | low | Pitch >20° down from baseline for 15+ s (writing is normal → low weight) |
| `looking_down_phone` | high | Looking down + any `cell phone` candidate (conf ≥0.30) in the same frame |
| `object_detected` | high | YOLO sees phone/book/laptop/remote (conf ≥0.65) |
| `audio_speech` | high | VAD speech ≥1 s in chunk AND ≥40% of last ~6 s (3 chunks); 1st & every 3rd batch |
| `audio_short_speech` | low | VAD speech ≥1 s but sustained ratio <40% (one-off phrase) |
| `audio_whispering` | medium | RMS in baseline-relative band AND speech-like rhythm (`ai/audio_features.py`), 2-3 consecutive |
| `tab_switch` / `fullscreen_exit` | medium | `visibilitychange` / `fullscreenchange` |
| `focus_lost` / `copy_attempt` | low | window blur / copy-cut-paste |
| `video_stalled` / `stream_lost` | high | server watchdog: no frame 6s / disconnected 10s+ |
| `audio_stalled` | medium | server watchdog: no audio 12s |
| `camera_ended` / `mic_ended` / `mic_denied` / `virtual_camera` | high | browser track/permission/label checks |

Points = severity weight (15/7/3) × confidence clamped to 0.5–1.0, capped at 100, decay 1pt/30s — computed
ONLY on the server and pushed to teachers (`meta: scores`). Dedup window 10s per event type. A classifier
`audio_talking`/`audio_multiple_voices` event suppresses the generic `audio_speech` in the same batch.

## Key engineering decisions

- **Sessions end only by submit or server deadline:** login/refresh/disconnect never end or reset a session (old "fresh login = clean state" was a cheating vector — audit P0-2). Deadline = `started_at + duration`; background loop auto-submits expired sessions (autosaved answers).
- **Retake policy:** a submitted exam can't be restarted unless the teacher "Цэвэрлэх" (decision=reset) it, or `ALLOW_RETAKE=1`.
- **One live connection per student:** a second tab replaces the first (close 4000); cleanup only touches its own connection object.
- **Live video to teacher:** Frame pushed as raw binary blob (no base64 JSON). Teacher writes `URL.createObjectURL(blob)` directly to `<img>.src` via ref — bypasses React re-renders.
- **Frame routing:** Student sends 5 fps (640px, skips if `bufferedAmount` > 1MB). Receive loop only stores the latest frame; a per-student worker analyzes it at 1 Hz (time-based). Teachers get frames through a `Queue(maxsize=1)` sender task so a slow teacher never stalls students.
- **Thread safety:** MediaPipe/YOLO/audio models are shared → guarded by locks in `analyzer.py`; FaceMesh uses `static_image_mode=True` so tracking state never leaks between students. ffmpeg decode + snapshot writes run in `asyncio.to_thread`.
- **Teacher watch/unwatch:** `{action: "watch", student_id}` subscribes to that student's frame stream. `unwatch` releases.
- **Event buffering:** Events queued (max 100) when teacher offline, replayed on reconnect.
- **Incident snapshots:** Every flag → JPEG saved to `models/incidents/{student_id}/{ts}_{event}.jpg`. Path stored in DB `snapshot` column. Teacher UI shows thumbnails + click-to-enlarge.
- **EBML handling:** WebM stream's EBML header is only in the first MediaRecorder chunk. Backend saves this and prepends to subsequent chunks for ffmpeg decoding. Recorder restarts on every WS reconnect to get fresh EBML.
- **Audio classifier limitation:** WavLM model trained to 98% accuracy on phone/studio recordings but predicts `normal` for browser WebM audio (domain mismatch). Production uses VAD+RMS heuristics. Honest finding for thesis.

## Pilot evaluation

`PILOT_MODE=1` (backend/.env) makes `/api/exam/start` return `backend/pilot_protocol.json`; the student exam page shows `components/PilotRunner.tsx` (instructions + beeps) and posts `/api/pilot/mark` per step → `pilot_marks` table (server time = ground truth). `scripts/evaluation/pilot_report.py` matches marks to `risk_events` by session_id → per-detector recall (step-level) / precision (event-level) / F1 with Wilson CI, latency, normal-period false alarms per hour. Guide: `scripts/evaluation/PILOT_GUIDE.md`. Off by default.

## Scalability & ops

- Load test (`scripts/loadtest/ws_load.py`, results `docs/LOAD_TEST.md`): ~10 students at full 1 Hz per process, 20–30 at ~0.8 Hz. YOLO is ~80% of per-frame cost; more threads/processes did not raise the ~15 frames/s ceiling, so YOLO runs every `OBJECT_EVERY`=2 analyses and thresholds are wall-clock (`_sustained` in analyzer).
- `AI_WORKERS` (default 2) = model pool size (MediaPipe/YOLO/VAD instances); WavLM single instance behind `_clf_lock`.
- `GET /api/metrics` (teacher): analysis ms p50/p95, per-student analysis rate, dropped audio/frames, RSS.
- `INCIDENTS_DIR` env overrides snapshot dir (load tests). `LIVENESS=0` disables challenges (auto-off in PILOT_MODE).
- Liveness (`ai/liveness.py`): random "turn head" challenge 60–180 s after connect then every 4–8 min; pass = |d_yaw| ≥ 20° within 8 s; fail → `liveness_failed` (medium, high if repeated).
- Login rate limit (`ratelimit.py`): 5 fails per IP+user / 20 per IP in 5 min → 429 for 5 min.
- Archive is a separate `ExamSession.archived` flag (it used to overwrite `decision`).
- Tests: `python -m pytest` (39 tests, light deps in `backend/requirements-dev.txt`), CI in `.github/workflows/tests.yml` (pytest + tsc for both apps).

## Tuning knobs

- `_DEDUP_WINDOW_SEC = 10` — same event type within 10s ignored
- `_DECAY_PER_TICK = 1.0`, `_DECAY_TICK_SEC = 30` — score decay rate
- Whisper detection: baseline-relative RMS band + `audio_features.is_speech_like` (energy concentration <0.5, envelope mod depth ≥0.3, 2–8 Hz syllabic share ≥0.4); impulsive chunks (keyboard, cough) never count as speech/whisper
- Classifier input: rolling last 5 s of PCM (`CLF_WINDOW_SEC`), not the zero-padded 2 s chunk
- Gaze (`backend/ai/gaze.py`): first 5 analyzed frames = per-student baseline (median, clamped to ±20°); baseline kept per session across reconnects; slow EMA drift capped at ±10°. Thresholds `YAW_THRESH_DEG=25`, `PITCH_DOWN/UP_THRESH_DEG=20`, `IRIS_THRESH=0.18`.
- AI analysis period: `_ANALYSIS_PERIOD = 1.0` s (so face_missing "X seconds" stays in seconds)
- Watchdog: `_VIDEO_STALL_SEC = 6`, `_AUDIO_STALL_SEC = 12`, `_STREAM_LOST_SEC = 10`

## Known limitations (for thesis recommendations section)

1. WavLM classifier doesn't generalize to browser audio → retraining with browser-recorded data needed
2. Single exam (`exam_001`) defined in `backend/exams.py` → multi-exam DB schema (Exam/Question tables)
3. Gaze thresholds (25°/20°) are heuristic — need tuning on labeled pilot data
5. SQLite → PostgreSQL for production scale
6. No incident snapshot cleanup → auto-delete on `cleared` decision or >30 days old
7. Audio feature thresholds validated only on synthetic signals — need real recordings (keyboard, fan, whisper) to tune

## Don'ts

- **Don't commit `data.zip`** (3.2GB) or `models/` (large) — already in .gitignore
- **Don't `npm audit fix --force`** before defense — might break Next.js
- **Don't claim "98% accuracy in production"** — that's training accuracy on different audio
- **Don't delete `models/incidents/`** — those are evidence files

## Decision history

- Started with WavLM cheating classifier (4 classes: normal/talking/multiple/whispering), achieved 98% accuracy in Colab with WeightedTrainer. Model doesn't transfer to browser audio → pivoted to VAD+RMS heuristic fallback.
- Originally polled video frames every 2s in teacher UI → switched to server-push binary blobs for smooth ~10fps preview.
- Originally created new session on every WS connect → caused refresh to reset risk score. Switched to session reuse with 60s grace period.
- Originally fetched all-time events for `/api/dashboard` → caused teacher to see old test data. Filtered to current-session events only.
