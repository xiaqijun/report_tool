import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get_bool_env(name: str, default: bool) -> bool:
	value = os.getenv(name)
	if value is None:
		return default
	return value.strip().lower() in {"1", "true", "yes", "on"}

DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
IMPORT_DIR = DATA_DIR / "imports"
EXPORT_DIR = DATA_DIR / "exports"

DATABASE_HOST = os.getenv("DATABASE_HOST", "127.0.0.1")
DATABASE_PORT = int(os.getenv("DATABASE_PORT", "3306"))
DATABASE_USER = os.getenv("DATABASE_USER", "root")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "")
DATABASE_NAME = os.getenv("DATABASE_NAME", "report_tool")
DATABASE_CHARSET = os.getenv("DATABASE_CHARSET", "utf8mb4")

APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
APP_RELOAD = _get_bool_env("APP_RELOAD", False)

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "Admin@123456")
