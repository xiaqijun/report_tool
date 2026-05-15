from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME, SECRET_KEY, ensure_runtime_dirs
from app.db import ensure_default_admin, init_db
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.web import router as web_router


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"


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
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(web_router)
    return app


app = create_app()
