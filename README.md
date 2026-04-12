# AI Proctor — Онлайн Шалгалтын Хяналтын Систем

## Хурдан эхлүүлэх

### 1. Docker ашиглан (Хамгийн хялбар)
```bash
docker-compose up
```

### 2. Гараар ажиллуулах
```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Student app (шинэ terminal)
cd apps/student
npm install && npm run dev

# Teacher app (шинэ terminal)
cd apps/teacher
npm install && npm run dev
```

## Хаягууд
- Суралцагч: http://localhost:3000
- Багш:      http://localhost:3001
- Backend:   http://localhost:8000

## Технологи
- Next.js 14 (TypeScript, Tailwind)
- FastAPI (Python)
- MediaPipe (нүүр илрүүлэлт)
- YOLOv8 (объект илрүүлэлт)
- WebSocket (шууд холболт)
- PostgreSQL

## Диплом: Г.Билгээ — СЭЗИС МСМ 2026
