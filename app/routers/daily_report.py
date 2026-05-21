import base64
import json
import re as _re
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import require_login
from app.db import (
    delete_ops_personnel,
    get_daily_report_by_date,
    get_llm_settings,
    get_ops_personnel,
    get_previous_report,
    list_ops_personnel,
    save_daily_report,
    save_llm_settings,
    save_ops_personnel,
)
from app.services.daily_report_ai import generate_top_section_text
from app.services.docx_generator import generate_daily_report_docx
from app.services.llm_settings import get_effective_llm_settings, mask_api_key, normalize_llm_settings
from scripts.import_docx_report import parse_docx


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.globals["asset_version"] = lambda: str(int((BASE_DIR / "app" / "static" / "app.css").stat().st_mtime))
router = APIRouter(tags=["daily-report"])

SCREENSHOT_FIELD_TO_SECTION = {
    "waf": "waf_screenshot_path",
    "cfw": "cfw_screenshot_path",
    "hss": "hss_screenshot_path",
    "ddos": "ddos_screenshot_path",
    "secmaster": "secmaster_screenshot_path",
    "emergency-response": "emergency_response_screenshot_path",
    "attack-path": "attack_path_screenshot_path",
    "key-work": "key_work_screenshot_path",
}

ALLOWED_SCREENSHOT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

NUMERIC_FIELDS = [
    "waf_attacks", "waf_blocked", "waf_ips_banned",
    "cfw_attacks", "cfw_unblocked",
    "hss_alerts", "ddos_cleanings", "ddos_blackholes", "secmaster_alerts",
    "waf_detail_attacks", "waf_detail_blocked", "waf_qps_peak_value",
    "cfw_detail_attacks", "cfw_detail_unblocked",
    "hss_detail_total", "hss_detail_fatal", "hss_detail_high",
    "hss_detail_medium", "hss_detail_low",
    "hss_unclosed_event_count",
    "ddos_detail_cleanings", "ddos_detail_blackholes",
    "secmaster_detail_total", "secmaster_detail_fatal", "secmaster_detail_high",
    "secmaster_detail_medium", "secmaster_detail_low", "secmaster_detail_info",
    "secmaster_unclosed_event_count",
]

SUMMARY_FIELD_MAPPINGS = {
    "waf_attacks": "waf_detail_attacks",
    "waf_blocked": "waf_detail_blocked",
    "cfw_attacks": "cfw_detail_attacks",
    "cfw_unblocked": "cfw_detail_unblocked",
    "hss_alerts": "hss_detail_total",
    "ddos_cleanings": "ddos_detail_cleanings",
    "ddos_blackholes": "ddos_detail_blackholes",
    "secmaster_alerts": "secmaster_detail_total",
}


def _pop_version_status(request: Request) -> dict[str, object]:
    return dict(request.session.pop("version_status", {}))


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _coerce_int(value: str) -> int:
    stripped = value.strip()
    if not stripped:
        return 0
    try:
        return int(stripped)
    except (ValueError, TypeError):
        return 0


def _compute_trends(current: dict[str, object], previous: dict[str, object] | None) -> dict[str, dict[str, object]]:
    if previous is None:
        return {}
    trends: dict[str, dict[str, object]] = {}
    for field in NUMERIC_FIELDS:
        cur_val = int(current.get(field, 0))
        prev_val = int(previous.get(field, 0))
        change = cur_val - prev_val
        pct = round((change / prev_val) * 100, 1) if prev_val != 0 else None
        trends[field] = {"change": change, "percent": pct}
    return trends


def _sanitize_screenshot_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in ALLOWED_SCREENSHOT_SUFFIXES else ".png"


def _save_screenshot(upload: UploadFile, report_date: str, stem: str) -> str:
    target_dir = BASE_DIR / "data" / "uploads" / "daily-report-screenshots" / report_date
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{stem}{_sanitize_screenshot_suffix(upload.filename)}"
    upload.file.seek(0)
    with target_path.open("wb") as target_file:
        shutil.copyfileobj(upload.file, target_file)
    return str(target_path.relative_to(BASE_DIR)).replace("\\", "/")


def _with_synced_summary_fields(report: dict[str, object] | None) -> dict[str, object] | None:
    if report is None:
        return None

    synced = dict(report)
    for summary_field, detail_field in SUMMARY_FIELD_MAPPINGS.items():
        synced[summary_field] = int(synced.get(detail_field, synced.get(summary_field, 0)) or 0)
    return synced


def _normalize_report_payload(payload: dict[str, object], existing_report: dict[str, object] | None = None) -> dict[str, object]:
    existing_report = existing_report or {}
    normalized = dict(payload)
    for field in NUMERIC_FIELDS:
        normalized[field] = _coerce_int(str(normalized.get(field, 0)))

    for summary_field, detail_field in SUMMARY_FIELD_MAPPINGS.items():
        normalized[summary_field] = int(normalized.get(detail_field, normalized.get(summary_field, 0)) or 0)

    for text_field in (
        "business_stability", "trend_comparison", "overall_assessment",
        "monitor_start", "monitor_end",
        "waf_qps_specs", "waf_qps_peak_range",
        "cfw_bandwidth_spec", "cfw_peak_inbound_range",
        "cfw_inbound_peak", "cfw_inbound_95th",
        "hss_closed_loop_status", "emergency_response",
        "attack_path_assessment", "key_work_content",
    ):
        normalized[text_field] = str(normalized.get(text_field, existing_report.get(text_field, ""))).strip()

    return normalized


def _build_llm_settings_payload(submitted: dict[str, object], current_settings: dict[str, object]) -> dict[str, object]:
    clear_api_key = str(submitted.get("clear_api_key", "")).strip().lower() in {"1", "true", "yes", "on"}
    api_key_input = str(submitted.get("api_key", "")).strip()
    preserved_api_key = str(current_settings.get("api_key", "")).strip() if current_settings.get("source") == "db" else ""
    api_key = ""
    if clear_api_key:
        api_key = ""
    elif api_key_input:
        api_key = api_key_input
    else:
        api_key = preserved_api_key

    return normalize_llm_settings(
        {
            "enabled": submitted.get("enabled"),
            "api_base_url": submitted.get("api_base_url", current_settings.get("api_base_url", "")),
            "api_key": api_key,
            "model": submitted.get("model", current_settings.get("model", "")),
            "timeout_seconds": submitted.get("timeout_seconds", current_settings.get("timeout_seconds", 30)),
        }
    )


def _llm_settings_status_text(settings: dict[str, object]) -> str:
    if not settings.get("enabled"):
        return "当前已关闭大模型生成，系统会自动使用本地兜底文案。"
    if settings.get("api_base_url") and settings.get("api_key") and settings.get("model"):
        return "当前配置完整，可直接用于日报顶部三段自动生成。"
    return "当前配置未填写完整，系统仍会回退到本地兜底文案。"


def _llm_settings_context(request: Request, current_user: dict[str, object], form_data: dict[str, object] | None = None, error_message: str = "") -> dict[str, object]:
    effective_settings = get_effective_llm_settings()
    stored_settings = get_llm_settings()
    display_settings = normalize_llm_settings(form_data) if form_data is not None else dict(effective_settings)
    display_settings["source"] = effective_settings.get("source", "env")
    return {
        "page_title": "大模型配置",
        "current_user": current_user,
        "llm_settings": display_settings,
        "llm_status_text": _llm_settings_status_text(display_settings),
        "llm_config_source": "数据库配置" if effective_settings.get("source") == "db" else ".env 默认配置",
        "llm_api_key_masked": mask_api_key(str(effective_settings.get("api_key", ""))),
        "has_stored_llm_settings": stored_settings is not None,
        "llm_settings_saved": request.session.pop("llm_settings_saved", ""),
        "error_message": error_message,
        "version_status": _pop_version_status(request),
    }


@router.get("/daily-report", response_class=HTMLResponse, response_model=None)
async def daily_report_form(request: Request) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    today = _today_str()
    report = _with_synced_summary_fields(get_daily_report_by_date(today))
    previous = _with_synced_summary_fields(get_previous_report(today))
    operators = list_ops_personnel()
    trends = _compute_trends(report or {}, previous)

    from datetime import timedelta
    yesterday = datetime.now() - timedelta(days=1)
    default_monitor_start = yesterday.strftime("%Y-%m-%d") + " 18:00"
    default_monitor_end = today + " 18:00"

    success_msg = request.session.pop("daily_report_saved", "")

    return templates.TemplateResponse(
        request=request,
        name="daily_report_form.html",
        context={
            "page_title": "安全日报",
            "current_user": current_user,
            "report_date": today,
            "report": report,
            "previous": previous,
            "operators": operators,
            "trends": trends,
            "default_monitor_start": default_monitor_start,
            "default_monitor_end": default_monitor_end,
            "default_waf_qps_specs": "85,000（云模式专业版45000+40个QPS扩展包）",
            "default_cfw_bandwidth_spec": "12050Mbps",
            "success_msg": success_msg,
            "version_status": _pop_version_status(request),
        },
    )


@router.post("/daily-report/save", response_model=None)
async def daily_report_save(request: Request) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    today = _today_str()
    form = await request.form()
    existing_report = get_daily_report_by_date(today) or {}

    payload: dict[str, object] = {}
    text_fields = [
        "business_stability", "trend_comparison", "overall_assessment",
        "monitor_start", "monitor_end",
        "waf_qps_specs", "waf_qps_peak_range",
        "cfw_bandwidth_spec", "cfw_peak_inbound_range",
        "cfw_inbound_peak", "cfw_inbound_95th",
        "hss_closed_loop_status",
        "emergency_response", "attack_path_assessment", "key_work_content",
    ]
    for field in text_fields:
        payload[field] = str(form.get(field, "")).strip()

    payload = _normalize_report_payload(payload, existing_report)

    for screenshot_field in SCREENSHOT_FIELD_TO_SECTION.values():
        upload = form.get(screenshot_field)
        paste_value = str(form.get(screenshot_field + "_value", "")).strip()
        if isinstance(upload, UploadFile) and upload.filename:
            payload[screenshot_field] = _save_screenshot(upload, today, screenshot_field.removesuffix("_path"))
        elif paste_value:
            payload[screenshot_field] = paste_value
        else:
            payload[screenshot_field] = str(existing_report.get(screenshot_field, ""))

    checkbox_fields = ["waf_exceeded_spec", "cfw_exceeded_spec"]
    for field in checkbox_fields:
        payload[field] = 1 if form.get(field) else 0

    save_daily_report(today, payload, current_user["display_name"])
    request.session["daily_report_saved"] = "日报保存成功"
    return RedirectResponse(url="/daily-report", status_code=302)


@router.post("/daily-report/generate-top-section", response_model=None)
async def daily_report_generate_top_section(request: Request) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    today = _today_str()
    existing_report = _with_synced_summary_fields(get_daily_report_by_date(today)) or {}
    previous_report = _with_synced_summary_fields(get_previous_report(today))
    body = await request.json()
    body_dict = body if isinstance(body, dict) else {}
    target_field = str(body_dict.get("target_field", "")).strip()
    report_payload = _normalize_report_payload(body_dict, existing_report)
    report_payload["report_date"] = today

    fields = (target_field,) if target_field else None
    return generate_top_section_text(report_payload, previous_report, fields=fields)


@router.get("/daily-report/preview", response_class=HTMLResponse, response_model=None)
async def daily_report_preview(request: Request) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    today = _today_str()
    report = _with_synced_summary_fields(get_daily_report_by_date(today))

    return templates.TemplateResponse(
        request=request,
        name="daily_report_preview.html",
        context={
            "page_title": "日报预览",
            "current_user": current_user,
            "report": report,
            "report_date": today,
            "preview_docx_url": "/daily-report/download?preview=1",
            "version_status": _pop_version_status(request),
        },
    )


@router.get("/daily-report/download", response_model=None)
async def daily_report_download(request: Request) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    today = _today_str()
    report = _with_synced_summary_fields(get_daily_report_by_date(today))
    if report is None:
        return RedirectResponse(url="/daily-report", status_code=302)

    operators = list_ops_personnel()
    file_path = generate_daily_report_docx(report, operators)
    return FileResponse(path=file_path, filename=file_path.name)


@router.get("/daily-report/screenshots/{report_date}/{section}", response_model=None)
async def daily_report_screenshot(request: Request, report_date: str, section: str) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    field_name = SCREENSHOT_FIELD_TO_SECTION.get(section)
    if field_name is None:
        raise HTTPException(status_code=404, detail="Screenshot section not found")

    report = get_daily_report_by_date(report_date)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    relative_path = str(report.get(field_name, "")).strip()
    if not relative_path:
        raise HTTPException(status_code=404, detail="Screenshot not found")

    file_path = BASE_DIR / relative_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Screenshot file missing")

    return FileResponse(path=file_path, filename=file_path.name)


@router.post("/daily-report/screenshots/paste", response_model=None)
async def daily_report_screenshot_paste(request: Request) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    body = await request.json()
    section = str(body.get("section", "")).strip()
    report_date = str(body.get("report_date", _today_str())).strip()
    image_data = str(body.get("image", "")).strip()

    field_name = SCREENSHOT_FIELD_TO_SECTION.get(section)
    if field_name is None or not image_data:
        raise HTTPException(status_code=400, detail="Invalid section or missing image data")

    header_match = _re.match(r"data:image/(\w+);base64,(.+)", image_data)
    if not header_match:
        raise HTTPException(status_code=400, detail="Invalid image data format")

    image_format = header_match.group(1)
    suffix = f".{image_format}" if image_format in {"png", "jpeg", "webp"} else ".png"
    raw_bytes = base64.b64decode(header_match.group(2))

    target_dir = BASE_DIR / "data" / "uploads" / "daily-report-screenshots" / report_date
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{field_name.removesuffix('_path')}{suffix}"
    target_path.write_bytes(raw_bytes)

    relative_path = str(target_path.relative_to(BASE_DIR)).replace("\\", "/")
    return JSONResponse({"path": relative_path})


@router.get("/daily-report/operators", response_class=HTMLResponse, response_model=None)
async def operators_page(request: Request, edit_id: int | None = None, create: int = 0) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    operators = list_ops_personnel()
    editing_record = get_ops_personnel(edit_id) if edit_id else None

    return templates.TemplateResponse(
        request=request,
        name="daily_report_operators.html",
        context={
            "page_title": "运营人员管理",
            "current_user": current_user,
            "operators": operators,
            "is_creating": bool(create),
            "editing_record": editing_record,
            "version_status": _pop_version_status(request),
        },
    )


@router.get("/daily-report/import", response_class=HTMLResponse, response_model=None)
async def daily_report_import_page(request: Request) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    return templates.TemplateResponse(
        request=request,
        name="daily_report_import.html",
        context={
            "page_title": "导入日报 DOCX",
            "current_user": current_user,
            "version_status": _pop_version_status(request),
        },
    )


@router.post("/daily-report/import", response_model=None)
async def daily_report_import(request: Request, file: UploadFile | None = None, report_date: str | None = Form(None), operator: str = Form("导入者")) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    if not file or not file.filename:
        return templates.TemplateResponse(
            request=request,
            name="daily_report_import.html",
            context={
                "page_title": "导入日报 DOCX",
                "current_user": current_user,
                "error_message": "请上传 DOCX 文件。",
                "version_status": _pop_version_status(request),
            },
            status_code=400,
        )

    target_dir = BASE_DIR / "data" / "imports"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / file.filename
    file.file.seek(0)
    with target_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # 尝试从文件名提取日期
    rd = report_date
    if not rd:
        m = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", file.filename)
        if m:
            rd = m.group(1)
    if not rd:
        # default to yesterday
        from datetime import datetime, timedelta

        rd = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        payload = parse_docx(target_path)
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="daily_report_import.html",
            context={
                "page_title": "导入日报 DOCX",
                "current_user": current_user,
                "error_message": f"解析 DOCX 失败: {exc}",
                "version_status": _pop_version_status(request),
            },
            status_code=500,
        )

    existing = get_daily_report_by_date(rd) or {}
    merged = dict(existing)
    merged.update(payload)

    save_daily_report(rd, merged, operator)
    request.session["daily_report_saved"] = f"导入并保存成功：{file.filename} -> {rd}"
    return RedirectResponse(url="/daily-report", status_code=302)


@router.get("/daily-report/llm-settings", response_class=HTMLResponse, response_model=None)
async def llm_settings_page(request: Request) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    return templates.TemplateResponse(
        request=request,
        name="daily_report_llm_settings.html",
        context=_llm_settings_context(request, current_user),
    )


@router.post("/daily-report/llm-settings/save", response_model=None)
async def llm_settings_save(
    request: Request,
    enabled: str | None = Form(None),
    api_base_url: str = Form(""),
    api_key: str = Form(""),
    clear_api_key: str | None = Form(None),
    model: str = Form(""),
    timeout_seconds: str = Form("30"),
) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    payload = _build_llm_settings_payload(
        {
            "enabled": enabled,
            "api_base_url": api_base_url,
            "api_key": api_key,
            "clear_api_key": clear_api_key,
            "model": model,
            "timeout_seconds": timeout_seconds,
        },
        get_effective_llm_settings(),
    )

    if payload["enabled"] and not (payload["api_base_url"] and payload["api_key"] and payload["model"]):
        return templates.TemplateResponse(
            request=request,
            name="daily_report_llm_settings.html",
            context=_llm_settings_context(
                request,
                current_user,
                form_data=payload,
                error_message="已启用大模型生成时，API 地址、API Key 和模型名称需同时填写完整。",
            ),
            status_code=400,
        )

    save_llm_settings(payload)
    request.session["llm_settings_saved"] = "大模型配置已保存"
    return RedirectResponse(url="/daily-report/llm-settings", status_code=302)


@router.post("/daily-report/operators/save", response_model=None)
async def operators_save(
    request: Request,
    record_id: str | None = Form(None),
    name: str = Form(""),
    phone: str = Form(""),
    role: str = Form(""),
    responsibility: str = Form(""),
    sort_order: str = Form("0"),
) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    parsed_id = None
    if record_id and record_id.strip():
        parsed_id = int(record_id.strip())

    save_ops_personnel(
        {
            "name": name.strip(),
            "phone": phone.strip(),
            "role": role.strip(),
            "responsibility": responsibility.strip(),
            "sort_order": sort_order.strip(),
        },
        parsed_id,
    )
    return RedirectResponse(url="/daily-report/operators", status_code=302)


@router.post("/daily-report/operators/{record_id}/delete", response_model=None)
async def operators_delete(request: Request, record_id: int) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    delete_ops_personnel(record_id)
    return RedirectResponse(url="/daily-report/operators", status_code=302)
