import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import DEFAULT_SECRET, settings
from .db import engine
from .errors import DomainError
from .logging_conf import configure_logging
from .routers import analytics, auth, episodes, requests, users

configure_logging()
access_log = logging.getLogger("drd.access")
log = logging.getLogger("drd")
if settings.secret_key == DEFAULT_SECRET:
    log.warning("SECRET_KEY is the insecure development default; set SECRET_KEY in production")

app = FastAPI(title="Dataset Request Desk", version="1.0.0")
STATIC = Path(__file__).parent / "static"


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    """One structured log line per request: method, path, status, duration, user id (when authenticated)."""
    start = time.perf_counter()
    request.state.user_id = None
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:  # unexpected bug: log the traceback once, return a clean 500, never leak internals
        log.exception("unhandled error", extra={"ctx": {"path": request.url.path}})
        response = JSONResponse({"detail": "Internal server error"}, status_code=500)
        status = 500
    request_id = uuid.uuid4().hex[:12]
    response.headers["X-Request-ID"] = request_id
    access_log.info(
        "request",
        extra={"ctx": {
            "method": request.method, "path": request.url.path, "status": status,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            "user_id": request.state.user_id, "request_id": request_id,
        }},
    )
    return response


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.get("/health", tags=["ops"])
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "unavailable", "database": "down"}, status_code=503)
    return {"status": "ok", "database": "up"}


for module in (auth, users, requests, episodes, analytics):
    app.include_router(module.router)

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
