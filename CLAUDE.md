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

Plaintext passwords — known weakness, acceptable for diploma. Bcrypt would be a future improvement.

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

- `backend/api/websocket.py` — student & teacher WS endpoints, event pipeline, frame routing, ffmpeg setup, session lifecycle (60s grace on disconnect for reconnect)
- `backend/api/routes.py` — REST endpoints: login, `/api/dashboard` (teacher rehydrate, current-session events only), `/api/session/.../current`, `/api/report/student/{id}.csv`, `/api/incident/{sid}/{file}` (snapshot serving)
- `backend/ai/analyzer.py` — `analyze_frame` (MediaPipe + YOLO) and `analyze_audio_samples` (VAD + classifier + RMS heuristics)
- `backend/db.py` — SQLAlchemy models: Student, Teacher, ExamSession, RiskEvent
- `backend/utils/log.py` — colored terminal logging (VAD speech/silence visually distinct)
- `apps/student/app/exam/page.tsx` — main exam UI, captures video at 10 fps + audio at 2s WebM chunks
- `apps/teacher/app/page.tsx` — dashboard, binary frame streaming, snapshot thumbnails

## Detection events (severity → risk score)

| Event | Severity | Trigger |
|---|---|---|
| `face_missing` | high (15pts) | No face for 5+ seconds |
| `multiple_faces` | high | >1 face in frame |
| `gaze_away` | medium (7pts) | Head turned away 10+ seconds |
| `object_detected` | high | YOLO sees phone/book/laptop/remote (conf ≥0.65) |
| `audio_speech` | high | VAD detects 1.5+ sec speech, fires on 1st & every 3rd batch |
| `audio_whispering` | medium | RMS 0.008–0.05 (quiet speech), needs 2-3 consecutive |
| `tab_switch` | medium | `visibilitychange` event |
| `copy_attempt` | low | Copy/paste blocked |

Risk score caps at 100 (backend `func.min`), decays 1pt/30sec. Dedup window 10s per event type.

## Key engineering decisions

- **Session reuse on reconnect:** WS disconnect → 60s grace → if same student reconnects, reuse existing session. Prevents risk score reset on transient network issues.
- **Fresh login = clean state:** Login endpoint ends any active session for that student. Frontend wipes localStorage answers/timer. New session starts at 0.
- **Live video to teacher:** Frame pushed as raw binary blob (no base64 JSON). Teacher writes `URL.createObjectURL(blob)` directly to `<img>.src` via ref — bypasses React re-renders.
- **Frame routing:** Student sends 10 fps → backend AI throttles to every 10th frame (1 fps for analysis) but forwards every frame to teacher when watching.
- **Teacher watch/unwatch:** `{action: "watch", student_id}` subscribes to that student's frame stream. `unwatch` releases.
- **Event buffering:** Events queued (max 100) when teacher offline, replayed on reconnect.
- **Incident snapshots:** Every flag → JPEG saved to `models/incidents/{student_id}/{ts}_{event}.jpg`. Path stored in DB `snapshot` column. Teacher UI shows thumbnails + click-to-enlarge.
- **EBML handling:** WebM stream's EBML header is only in the first MediaRecorder chunk. Backend saves this and prepends to subsequent chunks for ffmpeg decoding. Recorder restarts on every WS reconnect to get fresh EBML.
- **Audio classifier limitation:** WavLM model trained to 98% accuracy on phone/studio recordings but predicts `normal` for browser WebM audio (domain mismatch). Production uses VAD+RMS heuristics. Honest finding for thesis.

## Tuning knobs

- `_DEDUP_WINDOW_SEC = 10` — same event type within 10s ignored
- `_DECAY_PER_TICK = 1.0`, `_DECAY_TICK_SEC = 30` — score decay rate
- Whisper detection: `rms 0.008–0.05`, needs 2-3 consecutive batches
- AI frame skip: every 10th frame (so face_missing "X seconds" stays in seconds)

## Known limitations (for thesis recommendations section)

1. WavLM classifier doesn't generalize to browser audio → retraining with browser-recorded data needed
2. Plaintext passwords → bcrypt
3. Single exam (`exam_001`) hardcoded → multi-exam DB schema
4. Questions hardcoded in `exam/page.tsx` → Exam/Question tables
5. SQLite → PostgreSQL for production scale
6. No incident snapshot cleanup → auto-delete on `cleared` decision or >30 days old
7. Some audio false positives (whisper threshold tuning)

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
