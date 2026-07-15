import json
from datetime import datetime, timedelta
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests

from app import db


SETTINGS_KEY = "tencent_docs_settings"
TENCENT_DOCS_BASE_URL = "https://docs.qq.com"
DEFAULT_RANGE = "A1:T500"


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
        "file_id": settings.get("file_id", ""),
        "sheet_id": settings.get("sheet_id", ""),
        "sheet_range": settings.get("sheet_range", DEFAULT_RANGE),
        "has_client_secret": bool(settings.get("client_secret")),
        "authorized": bool(settings.get("access_token") and settings.get("open_id")),
        "open_id": settings.get("open_id", ""),
        "token_expires_at": settings.get("token_expires_at", ""),
        "last_sync_at": settings.get("last_sync_at", ""),
        "last_sync_count": settings.get("last_sync_count", 0),
    }


def save_configuration(payload: dict[str, object]) -> dict[str, object]:
    settings = get_settings()
    for key in ("client_id", "redirect_uri", "sheet_id", "sheet_range"):
        if key in payload:
            settings[key] = str(payload.get(key, "") or "").strip()

    source = str(payload.get("file_id", payload.get("document_url", "")) or "").strip()
    if source:
        settings["file_id"] = extract_file_id(source)

    client_secret = str(payload.get("client_secret", "") or "").strip()
    if client_secret:
        settings["client_secret"] = client_secret

    settings["sheet_range"] = str(settings.get("sheet_range") or DEFAULT_RANGE).strip()
    _save_settings(settings)
    return get_public_settings()


def extract_file_id(value: str) -> str:
    source = value.strip()
    if not source:
        return ""
    if "://" not in source:
        return source

    parsed = urlparse(source)
    path_parts = [part for part in parsed.path.split("/") if part]
    for marker in ("sheet", "sheets"):
        if marker in path_parts:
            index = path_parts.index(marker)
            if index + 1 < len(path_parts):
                return path_parts[index + 1]

    query = parse_qs(parsed.query)
    for key in ("fileId", "file_id", "id"):
        if query.get(key):
            return query[key][0]
    raise ValueError("无法从腾讯文档链接中识别在线表格 File ID。")


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


def sync_container_nodes() -> dict[str, object]:
    settings = _ensure_access_token()
    headers = {
        "Access-Token": str(settings["access_token"]),
        "Client-Id": str(settings["client_id"]),
        "Open-Id": str(settings["open_id"]),
    }
    file_id = extract_file_id(str(settings.get("file_id", "")))
    if not file_id:
        raise ValueError("请配置腾讯文档在线表格链接或 File ID。")

    sheet_id = str(settings.get("sheet_id", "") or "").strip()
    if not sheet_id:
        workbook = _request_json(
            f"/openapi/spreadsheet/v3/files/{quote(file_id, safe='$')}",
            headers=headers,
            params={"concise": 1},
        )
        workbook_data = _unwrap_data(workbook)
        properties = workbook_data.get("properties", []) if isinstance(workbook_data, dict) else []
        if not properties:
            raise ValueError("腾讯文档在线表格中没有可读取的工作表。")
        sheet_id = str(properties[0].get("sheetId", "") or "").strip()
        settings["sheet_id"] = sheet_id

    sheet_range = str(settings.get("sheet_range", DEFAULT_RANGE) or DEFAULT_RANGE).strip()
    response = _request_json(
        f"/openapi/spreadsheet/v3/files/{quote(file_id, safe='$')}/{quote(sheet_id, safe='')}/{quote(sheet_range, safe=':')}",
        headers=headers,
    )
    response_data = _unwrap_data(response)
    grid_data = response_data.get("gridData", {}) if isinstance(response_data, dict) else {}
    rows = grid_data_to_records(grid_data)
    count = db.import_dataset_records("unprotected-container-nodes", rows)

    settings["file_id"] = file_id
    settings["sheet_id"] = sheet_id
    settings["last_sync_at"] = datetime.now().isoformat(timespec="seconds")
    settings["last_sync_count"] = count
    _save_settings(settings)
    return {"count": count, "source_rows": len(rows), "sheet_id": sheet_id, "sheet_range": sheet_range}


def grid_data_to_records(grid_data: object) -> list[dict[str, str]]:
    if not isinstance(grid_data, dict):
        return []
    matrix: list[list[str]] = []
    for row in grid_data.get("rows", []):
        if not isinstance(row, dict):
            continue
        values = row.get("values", [])
        matrix.append([_cell_text(cell) for cell in values] if isinstance(values, list) else [])
    if not matrix:
        return []

    headers = [value.strip() for value in matrix[0]]
    records: list[dict[str, str]] = []
    for values in matrix[1:]:
        record = {
            header: values[index].strip() if index < len(values) else ""
            for index, header in enumerate(headers)
            if header
        }
        if any(record.values()):
            records.append(record)
    return records


def _cell_text(cell: object) -> str:
    if not isinstance(cell, dict):
        return ""
    cell_value = cell.get("cellValue", {})
    if isinstance(cell_value, (str, int, float, bool)):
        return str(cell_value)
    if not isinstance(cell_value, dict):
        return ""
    for key in ("text", "number", "boolean", "value", "formattedValue"):
        value = cell_value.get(key)
        if value is not None:
            return str(value)
    return ""


def _ensure_access_token() -> dict[str, object]:
    settings = _require_configuration()
    if not settings.get("access_token") or not settings.get("open_id"):
        raise ValueError("请先完成腾讯文档 OAuth 授权。")

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
    path: str, *, params: dict[str, object] | None = None, headers: dict[str, str] | None = None
) -> dict[str, object]:
    response = requests.get(
        f"{TENCENT_DOCS_BASE_URL}{path}",
        params=params,
        headers={"Accept": "application/json", **(headers or {})},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("腾讯文档接口返回了无法识别的数据。")
    error_code = data.get("ret", data.get("code", 0))
    if error_code not in (0, None):
        raise ValueError(str(data.get("msg", data.get("message", f"腾讯文档接口错误：{error_code}"))))
    return data


def _unwrap_data(payload: dict[str, object]) -> dict[str, object]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _save_settings(settings: dict[str, object]) -> None:
    db.save_app_setting(SETTINGS_KEY, json.dumps(settings, ensure_ascii=False))
