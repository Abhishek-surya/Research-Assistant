import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load .env with absolute path, but without overriding existing OS env vars (like Render production vars)
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(dotenv_path=env_path)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler
from api.routes import upload, documents, scrape, chat, history
from core.firebase import init_firebase
from services.embedding_scheduler import process_pending_chunks

import logging
logging.basicConfig(level=logging.INFO)

# ── APScheduler: batch embed every 2 minutes ──────────────────────────
scheduler = BackgroundScheduler()
scheduler.add_job(
    process_pending_chunks,
    trigger="interval",
    minutes=2,
    id="embed_pending_chunks",
    max_instances=1,          # prevent overlap if a run takes > 2 min
    misfire_grace_time=30,    # tolerate up to 30s late start
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_firebase()
    scheduler.start()
    logging.info("✅ Embedding scheduler started — runs every 2 minutes.")
    yield
    # Shutdown
    scheduler.shutdown(wait=False)
    logging.info("🛑 Embedding scheduler stopped.")

app = FastAPI(title="AI Research Assistant API", lifespan=lifespan)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(scrape.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(history.router, prefix="/api")

# Global handler so unhandled 500s always include CORS headers
# (without this, the browser reports 500s as a CORS failure)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    origin = request.headers.get("origin", "*")
    logging.exception(f"Unhandled error on {request.method} {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {str(exc)}"},
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
        },
    )

@app.get("/")
def read_root():
    return {"status": "ok", "message": "FastAPI is running!"}
