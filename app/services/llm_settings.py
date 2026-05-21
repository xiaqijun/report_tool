from app.config import LLM_API_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT_SECONDS
from app.db import get_llm_settings as get_stored_llm_settings


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _coerce_timeout(value: object, default: int = 30) -> int:
    try:
        timeout = int(value or default)
    except (TypeError, ValueError):
        timeout = default
    return max(1, timeout)


def normalize_llm_settings(payload: dict[str, object] | None) -> dict[str, object]:
    payload = payload or {}
    return {
        "enabled": _coerce_bool(payload.get("enabled", False)),
        "api_base_url": str(payload.get("api_base_url", "")).strip().rstrip("/"),
        "api_key": str(payload.get("api_key", "")).strip(),
        "model": str(payload.get("model", "")).strip(),
        "timeout_seconds": _coerce_timeout(payload.get("timeout_seconds", 30), default=30),
    }


def get_env_llm_settings() -> dict[str, object]:
    return normalize_llm_settings(
        {
            "enabled": bool(LLM_API_BASE_URL and LLM_API_KEY and LLM_MODEL),
            "api_base_url": LLM_API_BASE_URL,
            "api_key": LLM_API_KEY,
            "model": LLM_MODEL,
            "timeout_seconds": LLM_TIMEOUT_SECONDS,
        }
    )


def get_effective_llm_settings() -> dict[str, object]:
    env_settings = get_env_llm_settings()
    try:
        stored_settings = get_stored_llm_settings()
    except Exception:
        stored_settings = None
    if stored_settings is None:
        return {**env_settings, "source": "env"}
    return {**normalize_llm_settings(stored_settings), "source": "db"}


def mask_api_key(api_key: str) -> str:
    value = api_key.strip()
    if not value:
        return "未配置"
    if len(value) <= 8:
        return value[:2] + "*" * max(len(value) - 2, 0)
    return f"{value[:4]}{'*' * 8}{value[-4:]}"