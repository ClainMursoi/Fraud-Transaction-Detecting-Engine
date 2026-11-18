"""FastAPI application entry point."""

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.routes import feedback, score, simulator as simulator_routes
from app.core.config import get_settings
from app.services.simulator import simulator

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run the synthetic transaction producer for the lifetime of the app."""
    simulator.start()
    try:
        yield
    finally:
        await simulator.stop()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(score.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(simulator_routes.router, prefix="/api/v1")

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """Serve the local scoring dashboard from the application root."""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/styles.css", include_in_schema=False)
def dashboard_styles() -> FileResponse:
    """Serve the dashboard stylesheet without requiring static-file setup."""
    return FileResponse(FRONTEND_DIR / "styles.css", media_type="text/css")


@app.get("/app.js", include_in_schema=False)
def dashboard_script() -> FileResponse:
    """Serve the dashboard JavaScript without requiring static-file setup."""
    return FileResponse(FRONTEND_DIR / "app.js", media_type="application/javascript")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Liveness endpoint; it does not imply model or dependency readiness."""
    return {"status": "ok"}
