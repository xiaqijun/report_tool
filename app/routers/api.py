"""JSON API endpoints for React frontend."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
import os

from ..auth import require_login
from .. import db

router = APIRouter(prefix="/api")


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login")
async def api_login(request: Request, body: LoginRequest):
    """Login endpoint for React frontend."""
    from ..security import verify_password
    from starlette.responses import Response

    user = db.get_user_by_username(body.username)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["display_name"] = user["display_name"]

    return {
        "success": True,
        "user": {
            "user_id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
        },
    }


@router.post("/logout")
async def api_logout(request: Request):
    """Logout endpoint."""
    request.session.clear()
    return {"success": True}


@router.get("/me")
async def api_me(request: Request):
    """Check authentication status."""
    user = require_login(request)
    if isinstance(user, dict):
        return {"authenticated": True, "user": user}
    return {"authenticated": False}


@router.get("/dashboard")
async def api_dashboard(request: Request):
    """Dashboard data."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    return {"user": user}


@router.post("/generate")
async def api_generate(request: Request, asset_file: UploadFile = File(...)):
    """Generate report from asset file."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    from ..services.inventory import generate_from_asset_file

    try:
        result = generate_from_asset_file(asset_file, user.get("display_name") or user["username"])
        return {
            "result": {
                "batch_code": result["batch_code"],
                "counts": result["counts"],
                "previews": result["previews"],
                "missing_owner_projects": result.get("missing_owner_projects", []),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/history")
async def api_history(request: Request, q: str = "", page: int = 1):
    """History list."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    records, total = db.list_result_histories(search=q, page=page)
    return {
        "records": records,
        "page": page,
        "total": total,
    }


@router.delete("/history/{batch_code}")
async def api_delete_history(request: Request, batch_code: str):
    """Delete history record."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    db.delete_result_history(batch_code)
    return {"success": True}


@router.get("/daily-report")
async def api_daily_report(request: Request):
    """Get daily report data."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    from datetime import date

    today = date.today().isoformat()
    report = db.get_daily_report_by_date(today)
    operators = db.list_ops_personnel()

    return {
        "report": report,
        "operators": operators,
        "report_date": today,
    }


@router.post("/daily-report/save")
async def api_save_daily_report(request: Request):
    """Save daily report."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    form = await request.form()
    data = dict(form)

    from datetime import date

    today = date.today().isoformat()
    db.save_daily_report(today, data)

    return {"success": True}


@router.get("/daily-report/download")
async def api_download_daily_report(request: Request):
    """Download daily report DOCX."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    from datetime import date
    from ..services.docx_generator import generate_daily_report_docx

    today = date.today().isoformat()
    report = db.get_daily_report_by_date(today)

    if not report:
        raise HTTPException(status_code=404, detail="今日日报尚未填写")

    file_path = generate_daily_report_docx(today, report)
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"安全运营日报-{today}.docx",
    )


@router.get("/operators")
async def api_operators(request: Request):
    """List operators."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    return db.list_ops_personnel()


@router.post("/operators")
async def api_create_operator(request: Request):
    """Create operator."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    data = await request.json()
    db.save_ops_personnel(data)
    return {"success": True}


@router.put("/operators/{operator_id}")
async def api_update_operator(request: Request, operator_id: int):
    """Update operator."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    data = await request.json()
    data["id"] = operator_id
    db.save_ops_personnel(data)
    return {"success": True}


@router.delete("/operators/{operator_id}")
async def api_delete_operator(request: Request, operator_id: int):
    """Delete operator."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    db.delete_ops_personnel(operator_id)
    return {"success": True}


@router.get("/llm-settings")
async def api_llm_settings(request: Request):
    """Get LLM settings."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    settings = db.get_llm_settings()
    return {"settings": settings}


@router.post("/llm-settings/save")
async def api_save_llm_settings(request: Request):
    """Save LLM settings."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    data = await request.json()
    db.save_llm_settings(data)
    return {"success": True}


@router.get("/admin/{dataset_key}")
async def api_admin_list(request: Request, dataset_key: str, q: str = "", page: int = 1):
    """List dataset records."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    if dataset_key not in db.DATASET_DEFINITIONS:
        raise HTTPException(status_code=404, detail="未知数据集")

    records, total = db.list_dataset_records(dataset_key, search=q, page=page)
    return {
        "records": records,
        "page": page,
        "total": total,
    }


@router.post("/admin/{dataset_key}")
async def api_admin_create(request: Request, dataset_key: str):
    """Create dataset record."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    if dataset_key not in db.DATASET_DEFINITIONS:
        raise HTTPException(status_code=404, detail="未知数据集")

    data = await request.json()
    db.save_dataset_record(dataset_key, data)
    return {"success": True}


@router.put("/admin/{dataset_key}/{record_id}")
async def api_admin_update(request: Request, dataset_key: str, record_id: int):
    """Update dataset record."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    if dataset_key not in db.DATASET_DEFINITIONS:
        raise HTTPException(status_code=404, detail="未知数据集")

    data = await request.json()
    data["id"] = record_id
    db.save_dataset_record(dataset_key, data)
    return {"success": True}


@router.delete("/admin/{dataset_key}/{record_id}")
async def api_admin_delete(request: Request, dataset_key: str, record_id: int):
    """Delete dataset record."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    if dataset_key not in db.DATASET_DEFINITIONS:
        raise HTTPException(status_code=404, detail="未知数据集")

    db.delete_dataset_record(dataset_key, record_id)
    return {"success": True}


@router.post("/admin/{dataset_key}/import")
async def api_admin_import(request: Request, dataset_key: str, import_file: UploadFile = File(...)):
    """Import dataset records."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    if dataset_key not in db.DATASET_DEFINITIONS:
        raise HTTPException(status_code=404, detail="未知数据集")

    try:
        count = db.import_dataset_records(dataset_key, import_file)
        return {"success": True, "count": count}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/change-password")
async def api_change_password(request: Request, body: ChangePasswordRequest):
    """Change password."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    from ..security import verify_password, hash_password

    current_user = db.get_user_by_id(user["user_id"])
    if not verify_password(body.current_password, current_user["password_hash"]):
        raise HTTPException(status_code=400, detail="当前密码错误")

    new_hash = hash_password(body.new_password)
    db.update_user_password(user["user_id"], new_hash)

    return {"success": True}


@router.post("/daily-report/screenshots/paste")
async def api_paste_screenshot(request: Request):
    """Paste screenshot upload."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    data = await request.json()
    section = data.get("section")
    report_date = data.get("report_date")
    image_data = data.get("image")

    if not all([section, report_date, image_data]):
        raise HTTPException(status_code=400, detail="参数不完整")

    import base64
    from datetime import date

    # Create directory
    upload_dir = f"data/uploads/daily-report-screenshots/{report_date}"
    os.makedirs(upload_dir, exist_ok=True)

    # Save image
    header, encoded = image_data.split(",", 1)
    ext = header.split("/")[1].split(";")[0]
    file_path = f"{upload_dir}/{section}.{ext}"

    with open(file_path, "wb") as f:
        f.write(base64.b64decode(encoded))

    return {"path": file_path}
