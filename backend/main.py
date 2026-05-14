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

app = FastAPI(title="AI Proctor", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(ws_router)
app.include_router(api_router, prefix="/api")

@app.get("/")
def root():
    return {"status": "running", "docs": "/docs"}
