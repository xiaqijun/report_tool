from pathlib import Path

from fastapi import APIRouter, File, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import get_session_user, require_login
from app.db import get_result_history, list_result_histories
from app.services.inventory import OUTPUT_COLUMNS, generate_from_asset_file, persist_upload


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

router = APIRouter()


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
        context={
            "page_title": "内网资产清单工具",
            "current_user": current_user,
            "result": None,
            "output_columns": OUTPUT_COLUMNS,
            "error_message": "",
        },
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
            context={
                "page_title": "内网资产清单工具",
                "current_user": current_user,
                "result": result,
                "output_columns": OUTPUT_COLUMNS,
                "error_message": "",
            },
        )
    except ValueError as error:
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "page_title": "内网资产清单工具",
                "current_user": current_user,
                "result": None,
                "output_columns": OUTPUT_COLUMNS,
                "error_message": str(error),
            },
            status_code=400,
        )


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

