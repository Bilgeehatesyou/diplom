import os
from pathlib import Path
from dotenv import load_dotenv

# .env-ийг бусад модуль (auth.SECRET_KEY, db.DATABASE_URL) импортлогдохоос ӨМНӨ ачаална
load_dotenv(Path(__file__).resolve().parent / ".env")

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db import init_db
from api.websocket import router as ws_router
from api.routes    import router as api_router
from utils.log import log_app

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log_app("AI Proctor backend эхэллээ ✓")
    yield

app = FastAPI(title="AI Proctor", version="1.1.0", lifespan=lifespan)

# Token нь Authorization header-ээр явдаг (cookie биш) тул credentials шаардлагагүй.
# Зөвхөн student/teacher app-ийн origin-ууд (localhost + дотоод сүлжээ) зөвшөөрөгдөнө.
_extra_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001",
                   "http://127.0.0.1:3000", "http://127.0.0.1:3001", *_extra_origins],
    allow_origin_regex=r"http://(192\.168|10)\.\d{1,3}\.\d{1,3}(\.\d{1,3})?:300[01]",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(ws_router)
app.include_router(api_router, prefix="/api")

@app.get("/")
def root():
    return {"status": "running", "docs": "/docs"}
