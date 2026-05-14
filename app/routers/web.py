from pathlib import Path

from fastapi import APIRouter, File, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import get_session_user, require_login
from app.db import get_result_history, list_result_histories
from app.services.inventory import OUTPUT_COLUMNS, generate_from_asset_file, persist_upload
from app.services.system_update import check_version, run_update


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.globals["asset_version"] = str(int((BASE_DIR / "app" / "static" / "app.css").stat().st_mtime))

router = APIRouter()


def _pop_version_status(request: Request) -> dict[str, object]:
    return dict(request.session.pop("version_status", {}))


def _dashboard_context(request: Request, current_user: dict[str, str], result: dict[str, object] | None = None, error_message: str = "") -> dict[str, object]:
    return {
        "page_title": "内网资产清单工具",
        "current_user": current_user,
        "result": result,
        "output_columns": OUTPUT_COLUMNS,
        "error_message": error_message,
        "version_status": _pop_version_status(request),
    }


def _normalize_return_to(return_to: str) -> str:
    if not return_to.startswith("/") or return_to.startswith("//"):
        return "/dashboard"
    return return_to


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> RedirectResponse:
    if get_session_user(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse, response_model=None)
async def dashboard(request: Request) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=_dashboard_context(request, current_user),
    )


@router.post("/generate", response_class=HTMLResponse, response_model=None)
async def generate(request: Request, asset_file: UploadFile = File(...)) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    file_name = Path(asset_file.filename or "").name
    if not file_name:
        return RedirectResponse(url="/dashboard", status_code=302)

    target_path = persist_upload(file_name, await asset_file.read())
    try:
        result = generate_from_asset_file(target_path, current_user["display_name"])
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context=_dashboard_context(request, current_user, result=result),
        )
    except ValueError as error:
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context=_dashboard_context(request, current_user, error_message=str(error)),
            status_code=400,
        )


@router.post("/system/update", response_class=HTMLResponse, response_model=None)
async def update_code(request: Request) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    form = await request.form()
    return_to = _normalize_return_to(str(form.get("return_to", "/dashboard")))
    update_result = run_update()
    update_result["action"] = "update"
    request.session["version_status"] = update_result
    return RedirectResponse(url=return_to, status_code=302)


@router.post("/system/version-check", response_model=None)
async def version_check(request: Request) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    form = await request.form()
    return_to = _normalize_return_to(str(form.get("return_to", "/dashboard")))
    version_status = check_version()
    version_status["action"] = "check"
    if bool(version_status.get("ok")) and bool(version_status.get("has_update")):
        version_status = run_update()
        version_status["action"] = "update"
    request.session["version_status"] = version_status
    return RedirectResponse(url=return_to, status_code=302)


@router.get("/history", response_class=HTMLResponse, response_model=None)
async def history_page(request: Request, q: str = "", page: int = 1) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    records, total = list_result_histories(q, page)
    total_pages = max(1, (total + 19) // 20)
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "page_title": "生成历史",
            "current_user": current_user,
            "records": records,
            "query": q,
            "page": page,
            "total_pages": total_pages,
            "version_status": _pop_version_status(request),
        },
    )


@router.get("/download/{batch_code}/{result_key}", response_model=None)
async def download_result(request: Request, batch_code: str, result_key: str) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    history = get_result_history(batch_code)
    if history is None:
        return RedirectResponse(url="/history", status_code=302)

    path_field_map = {
        "online-unprotected": "online_unprotected_path",
        "agent-missing": "agent_missing_path",
        "protection-interrupted": "protection_interrupted_path",
    }
    path_field = path_field_map.get(result_key)
    if path_field is None:
        return RedirectResponse(url="/history", status_code=302)

    file_path = Path(str(history[path_field]))
    if not file_path.exists():
        return RedirectResponse(url="/history", status_code=302)
    return FileResponse(path=file_path, filename=file_path.name)

