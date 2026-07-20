import hashlib
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests

from app import db


SETTINGS_KEY = "tencent_docs_settings"
TENCENT_DOCS_BASE_URL = "https://docs.qq.com"
IMPORT_PROGRESS_ATTEMPTS = 60
IMPORT_PROGRESS_INTERVAL_SECONDS = 0.5

HISTORY_DOCUMENTS = {
    "online_unprotected": (
        "online_unprotected_path",
        "tencent_online_unprotected_url",
        "在线未防护",
    ),
    "agent_missing": (
        "agent_missing_path",
        "tencent_agent_missing_url",
        "Agent 未安装",
    ),
    "protection_interrupted": (
        "protection_interrupted_path",
        "tencent_protection_interrupted_url",
        "防护中断",
    ),
}


def get_settings() -> dict[str, object]:
    raw_value = db.get_app_setting(SETTINGS_KEY)
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def get_public_settings() -> dict[str, object]:
    settings = get_settings()
    return {
        "client_id": settings.get("client_id", ""),
        "redirect_uri": settings.get("redirect_uri", ""),
        "parent_folder_id": settings.get("parent_folder_id", ""),
        "has_client_secret": bool(settings.get("client_secret")),
        "authorized": bool(settings.get("access_token") and settings.get("open_id")),
        "token_expires_at": settings.get("token_expires_at", ""),
    }


def save_configuration(payload: dict[str, object]) -> dict[str, object]:
    settings = get_settings()
    for key in ("client_id", "redirect_uri", "parent_folder_id"):
        if key in payload:
            settings[key] = str(payload.get(key, "") or "").strip()

    client_secret = str(payload.get("client_secret", "") or "").strip()
    if client_secret:
        settings["client_secret"] = client_secret

    _save_settings(settings)
    return get_public_settings()


def build_authorize_url(state: str) -> str:
    settings = _require_configuration(require_secret=False)
    redirect_uri = str(settings["redirect_uri"])
    if not redirect_uri.lower().startswith("https://"):
        raise ValueError("腾讯文档 OAuth 回调地址必须使用 HTTPS。")
    query = urlencode(
        {
            "client_id": settings["client_id"],
            "redirect_uri": redirect_uri,
            "new_login": "1",
            "response_type": "code",
            "scope": "all",
            "state": state,
        }
    )
    return f"{TENCENT_DOCS_BASE_URL}/oauth/v2/authorize?{query}"


def exchange_authorization_code(code: str) -> dict[str, object]:
    settings = _require_configuration()
    token_data = _request_json(
        "GET",
        "/oauth/v2/token",
        params={
            "client_id": settings["client_id"],
            "client_secret": settings["client_secret"],
            "redirect_uri": settings["redirect_uri"],
            "grant_type": "authorization_code",
            "code": code,
        },
    )
    _store_token_response(settings, token_data, preserve_refresh_token=False)
    return get_public_settings()


def sync_history_documents(batch_code: str) -> dict[str, object]:
    history = db.get_result_history(batch_code)
    if history is None:
        raise ValueError("未找到对应的生成历史记录。")

    settings = _ensure_access_token()
    headers = _auth_headers(settings)
    links: dict[str, str] = {}

    for result_key, (path_field, url_field, title) in HISTORY_DOCUMENTS.items():
        existing_url = str(history.get(url_field, "") or "").strip()
        if existing_url:
            links[result_key] = existing_url
            continue

        file_path = Path(str(history.get(path_field, "") or ""))
        if not file_path.is_file():
            raise ValueError(f"{title}文件不存在：{file_path}")
        imported = _import_document(file_path, settings, headers)
        links[result_key] = str(imported["url"])

    db.update_result_history_tencent_docs(
        batch_code,
        links["online_unprotected"],
        links["agent_missing"],
        links["protection_interrupted"],
    )
    return {"batch_code": batch_code, "links": links, "count": len(links)}


def _import_document(
    file_path: Path,
    settings: dict[str, object],
    headers: dict[str, str],
) -> dict[str, str]:
    content = file_path.read_bytes()
    file_md5 = hashlib.md5(content).hexdigest()
    pre_import = _request_json(
        "POST",
        "/openapi/drive/v2/files/upload",
        headers=headers,
        data={
            "fileMD5": file_md5,
            "fileName": file_path.name,
            "fileSize": len(content),
        },
    )
    pre_import_data = _unwrap_data(pre_import)
    cos_put_url = str(pre_import_data.get("COSPutURL", "") or "")
    cos_file_key = str(pre_import_data.get("COSFileKey", "") or "")
    custom_headers = pre_import_data.get("CustomHeader", {})
    if not cos_put_url or not cos_file_key or not isinstance(custom_headers, dict):
        raise ValueError("腾讯文档预导入响应缺少 COS 上传信息。")
    _validate_cos_put_url(cos_put_url)

    upload_response = requests.put(
        cos_put_url,
        headers={str(key): str(value) for key, value in custom_headers.items()},
        data=content,
        timeout=120,
    )
    upload_response.raise_for_status()

    import_payload: dict[str, object] = {
        "fileMD5": file_md5,
        "fileName": file_path.name,
        "COSFileKey": cos_file_key,
    }
    parent_folder_id = str(settings.get("parent_folder_id", "") or "").strip()
    if parent_folder_id:
        import_payload["parentfolderID"] = parent_folder_id

    async_import = _request_json(
        "POST",
        "/openapi/drive/v2/files/async-import",
        headers=headers,
        data=import_payload,
    )
    progress_query_id = str(_unwrap_data(async_import).get("progressQueryID", "") or "")
    if not progress_query_id:
        raise ValueError("腾讯文档异步导入响应缺少进度查询凭证。")

    for _ in range(IMPORT_PROGRESS_ATTEMPTS):
        progress_response = _request_json(
            "GET",
            "/openapi/drive/v2/files/import-progress",
            headers=headers,
            params={"progressQueryID": progress_query_id},
        )
        progress_data = _unwrap_data(progress_response)
        progress = int(progress_data.get("progress", 0) or 0)
        document_url = str(progress_data.get("url", "") or "")
        if progress >= 100:
            if not document_url:
                raise ValueError("腾讯文档导入已完成，但未返回文档链接。")
            return {
                "id": str(progress_data.get("ID", "") or ""),
                "title": str(progress_data.get("title", file_path.stem) or file_path.stem),
                "url": document_url,
            }
        time.sleep(IMPORT_PROGRESS_INTERVAL_SECONDS)

    raise TimeoutError(f"腾讯文档导入超时：{file_path.name}")


def _auth_headers(settings: dict[str, object]) -> dict[str, str]:
    return {
        "Access-Token": str(settings["access_token"]),
        "Client-Id": str(settings["client_id"]),
        "Open-Id": str(settings["open_id"]),
    }


def _validate_cos_put_url(value: str) -> None:
    parsed = urlparse(value)
    hostname = str(parsed.hostname or "").lower()
    if parsed.scheme != "https" or not hostname.endswith(".myqcloud.com"):
        raise ValueError("腾讯文档返回了不可信的 COS 上传地址。")


def _ensure_access_token() -> dict[str, object]:
    settings = get_settings()
    missing = [
        key
        for key in ("client_id", "access_token", "open_id")
        if not str(settings.get(key, "") or "").strip()
    ]
    if missing:
        raise ValueError(f"腾讯文档访问配置不完整：{', '.join(missing)}")

    expires_at = str(settings.get("token_expires_at", "") or "")
    if expires_at:
        try:
            needs_refresh = datetime.fromisoformat(expires_at) <= datetime.now() + timedelta(minutes=5)
        except ValueError:
            needs_refresh = True
        if needs_refresh:
            settings = _refresh_access_token(settings)
    return settings


def _refresh_access_token(settings: dict[str, object]) -> dict[str, object]:
    refresh_token = str(settings.get("refresh_token", "") or "")
    if not refresh_token:
        raise ValueError("腾讯文档授权已过期，请重新授权。")
    token_data = _request_json(
        "GET",
        "/oauth/v2/token",
        params={
            "client_id": settings["client_id"],
            "client_secret": settings["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    return _store_token_response(settings, token_data, preserve_refresh_token=True)


def _store_token_response(
    settings: dict[str, object], token_data: dict[str, object], *, preserve_refresh_token: bool
) -> dict[str, object]:
    access_token = str(token_data.get("access_token", "") or "")
    open_id = str(token_data.get("user_id", token_data.get("open_id", "")) or "")
    if not access_token or not open_id:
        raise ValueError("腾讯文档授权响应缺少 Access Token 或 Open ID。")
    settings["access_token"] = access_token
    settings["open_id"] = open_id
    refresh_token = str(token_data.get("refresh_token", "") or "")
    if refresh_token or not preserve_refresh_token:
        settings["refresh_token"] = refresh_token
    expires_in = int(token_data.get("expires_in", 0) or 0)
    settings["token_expires_at"] = (datetime.now() + timedelta(seconds=max(expires_in, 0))).isoformat(timespec="seconds")
    _save_settings(settings)
    return settings


def _require_configuration(*, require_secret: bool = True) -> dict[str, object]:
    settings = get_settings()
    required = ["client_id", "redirect_uri"]
    if require_secret:
        required.append("client_secret")
    missing = [key for key in required if not str(settings.get(key, "") or "").strip()]
    if missing:
        raise ValueError(f"腾讯文档配置不完整：{', '.join(missing)}")
    return settings


def _request_json(
    method: str,
    path: str,
    *,
    params: dict[str, object] | None = None,
    data: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    response = requests.request(
        method,
        f"{TENCENT_DOCS_BASE_URL}{path}",
        params=params,
        data=data,
        headers={"Accept": "application/json", **(headers or {})},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("腾讯文档接口返回了无法识别的数据。")
    error_code = payload.get("ret", payload.get("code", 0))
    if error_code not in (0, None):
        raise ValueError(str(payload.get("msg", payload.get("message", f"腾讯文档接口错误：{error_code}"))))
    return payload


def _unwrap_data(payload: dict[str, object]) -> dict[str, object]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _save_settings(settings: dict[str, object]) -> None:
    db.save_app_setting(SETTINGS_KEY, json.dumps(settings, ensure_ascii=False))
