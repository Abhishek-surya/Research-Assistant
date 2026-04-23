import os
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load .env without overriding existing OS env vars (like Render production vars)
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(dotenv_path=env_path)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import upload, documents, scrape, chat, history, jobs
from core.firebase import init_firebase

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

from apscheduler.schedulers.background import BackgroundScheduler
from services.embedding_scheduler import process_pending_chunks

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize critical services
    print("🚀 [STARTUP] Initializing AI Research Assistant Backend...")
    try:
        init_firebase()
        logger.info("✅ Firebase initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Firebase: {e}")
    
    scheduler = BackgroundScheduler()
    # Runs quietly in background...
    scheduler.add_job(process_pending_chunks, "interval", minutes=2)
    scheduler.start()
    logger.info("✅ APScheduler started for background embedding.")
    
    yield
    # Shutdown logic
    logger.info("🛑 [SHUTDOWN] Application shutting down.")
    scheduler.shutdown()

app = FastAPI(
    title="AI Research Assistant API",
    description="Production-ready FastAPI backend",
    lifespan=lifespan
)

# Configure CORS with specific production origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ai-research-assistant-3d978.web.app",
        "https://ai-research-assistant-3d978.firebaseapp.com",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set Cross-Origin-Opener-Policy for Auth/Popup compatibility
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    response.headers["Cross-Origin-Embedder-Policy"] = "unsafe-none"
    return response

# Routes
app.include_router(upload.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(scrape.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    origin = request.headers.get("origin", "*")
    logger.exception(f"Unhandled error on {request.method} {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please check backend logs."},
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
        },
    )

@app.get("/")
async def health_check():
    """
    Standard health check endpoint for Render/Cloudflare.
    """
    logger.info("💓 Health check received at /")
    return {
        "status": "healthy",
        "service": "AI Research Assistant API",
        "utc_time": datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    # Use $PORT from environment (default to 10000 for local/Render default)
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
