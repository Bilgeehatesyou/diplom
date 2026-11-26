# AI Proctor — Онлайн шалгалтын хяналтын систем

Оюутан browser-оор шалгалт өгөхөд backend нь камер (нүүр, харц, олон хүн, хориотой объект) болон
микрофоны (яриа, шивнээ) урсгалыг бодит хугацаанд шинжилж, багшийн самбарт эрсдэлийн оноо,
нотлох зурагтай зөрчлийг харуулна. Эцсийн шийдвэрийг багш гаргана (human-in-the-loop).

## Технологи
- **Backend:** FastAPI + WebSocket (Python 3.11), SQLite (`backend/aiproctor.db`, SQLAlchemy async)
- **AI:** MediaPipe (нүүр/харц), YOLOv8n (объект), Silero VAD + RMS heuristic (яриа/шивнээ), WavLM classifier (туршилтын)
- **Frontend:** Next.js 14 (TypeScript, Tailwind) — `apps/student` (:3000), `apps/teacher` (:3001)
- **Аюулгүй байдал:** JWT (HS256) + role-based access, bcrypt нууц үг

## Анх суулгах
1. Python 3.11, Node.js 20, **ffmpeg** (`winget install ffmpeg` / `brew install ffmpeg`)
2. `python -m venv .venv` → `.venv\Scripts\activate` → `pip install -r backend/requirements.txt`
3. `npm install` — `apps/student` болон `apps/teacher` дотор
4. `backend/.env` үүсгэх:
   ```
   SECRET_KEY=<32+ тэмдэгттэй санамсаргүй мөр>
   # Сонголттой:
   # EXAM_DURATION_SEC=3000      # шалгалтын хугацаа (default 50 мин)
   # ALLOW_RETAKE=1              # demo үед илгээсэн шалгалтыг дахин өгөхийг зөвшөөрөх
   # CORS_ORIGINS=http://my-host:3000
   ```
   `SECRET_KEY` байхгүй бол сервер түр түлхүүр үүсгэнэ (restart бүрд дахин нэвтрэх шаардлагатай).
5. Загварын файлууд (gitignore-д орсон, гараар хуулна): `backend/yolov8n.pt`, `models/cheating_classifier_v3/`

## Ажиллуулах
```bash
# Backend
cd backend && uvicorn main:app --port 8000
# Student app
cd apps/student && npm run dev
# Teacher app
cd apps/teacher && npm run dev
```
Docker: `SECRET_KEY=... docker-compose up`

Хаяг: оюутан http://localhost:3000 · багш http://localhost:3001 · API http://localhost:8000/docs

Анхны бүртгэл (seed): оюутан `B22FA1260` / багш `Tsetsegee`, нууц үг `123456` (bcrypt-ээр хадгалагдана).

## Шалгалтын урсгал
1. Оюутан нэвтэрнэ → JWT авна → нөхцөлийг зөвшөөрч, бүтэн дэлгэцээр эхэлнэ.
2. `POST /api/exam/start` — сервер session үүсгэнэ (эсвэл идэвхтэйг үргэлжлүүлнэ). Асуулт, үлдсэн хугацаа серверээс ирнэ.
3. Хариулт автоматаар серверт хадгалагдана (`PUT /api/exam/answers`); refresh, дахин нэвтрэх, сүлжээ тасрах нь оноо/таймерыг reset хийхгүй.
4. `POST /api/exam/submit` эсвэл хугацаа дуусахад сервер session-ийг хаана. Илгээсэн шалгалтыг дахин өгөхийн тулд багш "Цэвэрлэх" хийнэ.

## Хяналтын event-үүд
| Event | Түвшин | Эх сурвалж |
|---|---|---|
| face_missing, multiple_faces, object_detected | high | Камер (сервер, 1 Hz) |
| gaze_away | medium | Камер |
| audio_speech / audio_talking / audio_multiple_voices | high | Микрофон |
| audio_whispering | medium | Микрофон |
| video_stalled / stream_lost | high | Серверийн watchdog (кадр 6с ирэхгүй / холболт 10с+ тасрах) |
| audio_stalled | medium | Серверийн watchdog |
| camera_ended, mic_ended, mic_denied, virtual_camera | high | Browser |
| tab_switch, fullscreen_exit | medium | Browser |
| focus_lost, copy_attempt | low | Browser |

Оноо = severity жин (15/7/3) × confidence (0.5–1.0), 100-д таслагдана, 30с тутам 1 оноо буурна. Оноог зөвхөн сервер тооцно.

## Диплом: Г.Билгээ — СЭЗИС МСМ 2026
