from pathlib import Path

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import require_login
from app.config import IMPORT_DIR
from app.db import DATASET_DEFINITIONS, delete_dataset_record, get_dataset_record, import_dataset_records, list_dataset_records, save_dataset_record
from app.services.spreadsheets import read_table_file


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.globals["asset_version"] = str(int((BASE_DIR / "app" / "static" / "app.css").stat().st_mtime))
router = APIRouter(prefix="/admin", tags=["admin"])


def _pop_version_status(request: Request) -> dict[str, object]:
    return dict(request.session.pop("version_status", {}))


@router.get("/{dataset_key}", response_class=HTMLResponse, response_model=None)
async def dataset_page(request: Request, dataset_key: str, q: str = "", page: int = 1, edit_id: int | None = None, create: int = 0) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user
    if dataset_key not in DATASET_DEFINITIONS:
        return RedirectResponse(url="/dashboard", status_code=302)

    definition = DATASET_DEFINITIONS[dataset_key]
    records, total = list_dataset_records(dataset_key, q, page)
    total_pages = max(1, (total + 19) // 20)
    return templates.TemplateResponse(
        request=request,
        name="admin_dataset.html",
        context={
            "page_title": definition["title"],
            "current_user": current_user,
            "dataset_key": dataset_key,
            "dataset": definition,
            "records": records,
            "query": q,
            "page": page,
            "total": total,
            "total_pages": total_pages,
            "is_creating": bool(create),
            "editing_record": get_dataset_record(dataset_key, edit_id) if edit_id else None,
            "version_status": _pop_version_status(request),
        },
    )


@router.post("/{dataset_key}/save", response_model=None)
async def save_dataset(request: Request, dataset_key: str, record_id: int | None = Form(None), enterprise_project: str = Form(""), owner_name: str = Form(""), server_id: str = Form(""), ip_address: str = Form(""), server_name: str = Form(""), note: str = Form("")) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user
    if dataset_key not in DATASET_DEFINITIONS:
        return RedirectResponse(url="/dashboard", status_code=302)

    save_dataset_record(
        dataset_key,
        {
            "enterprise_project": enterprise_project.strip(),
            "owner_name": owner_name.strip(),
            "server_id": server_id.strip(),
            "ip_address": ip_address.strip(),
            "server_name": server_name.strip(),
            "note": note.strip(),
        },
        record_id,
    )
    return RedirectResponse(url=f"/admin/{dataset_key}", status_code=302)


@router.post("/{dataset_key}/{record_id}/delete", response_model=None)
async def delete_dataset(request: Request, dataset_key: str, record_id: int) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user
    if dataset_key in DATASET_DEFINITIONS:
        delete_dataset_record(dataset_key, record_id)
    return RedirectResponse(url=f"/admin/{dataset_key}", status_code=302)


@router.post("/{dataset_key}/import", response_model=None)
async def import_dataset(request: Request, dataset_key: str, import_file: UploadFile = File(...)) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user
    if dataset_key not in DATASET_DEFINITIONS:
        return RedirectResponse(url="/dashboard", status_code=302)

    file_name = Path(import_file.filename or "").name
    if not file_name:
        return RedirectResponse(url=f"/admin/{dataset_key}", status_code=302)

    target_path = IMPORT_DIR / file_name
    target_path.write_bytes(await import_file.read())
    rows = read_table_file(target_path)
    import_dataset_records(dataset_key, rows)
    return RedirectResponse(url=f"/admin/{dataset_key}", status_code=302)