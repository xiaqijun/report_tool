from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, Response as FResponse
from starlette.middleware.sessions import SessionMiddleware

from app.config import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME, SECRET_KEY, ensure_runtime_dirs
from app.db import ensure_default_admin, init_db, get_result_history
from app.auth import require_login
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

    # File download route (legacy, used by React frontend)
    @app.get("/download/{batch_code}/{result_key}")
    async def download_result(request: Request, batch_code: str, result_key: str):
        """Download result file."""
        current_user = require_login(request)
        if not isinstance(current_user, dict):
            return RedirectResponse(url="/login", status_code=302)

        history = get_result_history(batch_code)
        if history is None:
            return RedirectResponse(url="/", status_code=302)

        path_field_map = {
            "online-unprotected": "online_unprotected_path",
            "agent-missing": "agent_missing_path",
            "protection-interrupted": "protection_interrupted_path",
        }
        path_field = path_field_map.get(result_key)
        if path_field is None:
            return RedirectResponse(url="/", status_code=302)

        file_path = Path(str(history[path_field]))
        if not file_path.exists():
            return RedirectResponse(url="/", status_code=302)
        return FileResponse(path=file_path, filename=file_path.name)

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
            # Skip download routes
            if path.startswith("download/"):
                raise HTTPException(status_code=404, detail="Not found")
            # Serve React index.html
            return FileResponse(REACT_DIR / "index.html")

    return app


app = create_app()
