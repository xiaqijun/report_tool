from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware

from app.config import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME, SECRET_KEY, ensure_runtime_dirs
from app.db import ensure_default_admin, init_db
from app.routers.admin import router as admin_router
from app.routers.api import router as api_router
from app.routers.auth import router as auth_router
from app.routers.daily_report import router as daily_report_router
from app.routers.web import router as web_router


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"
REACT_DIR = STATIC_DIR / "react"


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_runtime_dirs()
    init_db()
    ensure_default_admin(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="报告管理工具", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    # app.include_router(auth_router)
    # app.include_router(admin_router)
    app.include_router(api_router)
    # app.include_router(web_router)
    # app.include_router(daily_report_router)

    # Serve React frontend
    if REACT_DIR.exists():
        app.mount("/assets", StaticFiles(directory=REACT_DIR / "assets"), name="react-assets")

        # Serve React index.html for root path
        @app.get("/")
        async def serve_react_root():
            """Serve React frontend for root path."""
            return FileResponse(REACT_DIR / "index.html")

        # Catch-all route to serve React index.html for SPA routing
        @app.get("/{path:path}")
        async def serve_react(request: Request, path: str):
            """Serve React frontend for all non-API routes."""
            # Skip API routes
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            # Skip static files
            if path.startswith("static/"):
                raise HTTPException(status_code=404, detail="Not found")
            # Serve React index.html
            return FileResponse(REACT_DIR / "index.html")

    return app


app = create_app()
