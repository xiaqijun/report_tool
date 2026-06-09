"""JSON API endpoints for React frontend."""

from pathlib import Path
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

    import io
    from ..services.inventory import generate_from_asset_file

    try:
        content = io.BytesIO(await asset_file.read())
        result = generate_from_asset_file(
            content,
            user.get("display_name") or user["username"],
            original_filename=asset_file.filename or "upload.xlsx",
        )
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

    import io
    from ..services.spreadsheets import read_table_file

    try:
        content = io.BytesIO(await import_file.read())
        rows = read_table_file(content, filename=import_file.filename or ".xlsx")
        count = db.import_dataset_records(dataset_key, rows)
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


@router.get("/email/settings")
async def api_get_email_settings(request: Request):
    """Get email settings."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    settings = db.get_email_settings()
    return {"settings": settings}


@router.post("/email/settings/save")
async def api_save_email_settings(request: Request):
    """Save email settings."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    data = await request.json()
    db.save_email_settings(data)
    return {"success": True}


@router.post("/email/test")
async def api_test_email(request: Request):
    """Test email connection."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    data = await request.json()
    from ..services.email_service import test_smtp_connection
    result = test_smtp_connection(data)
    return result


@router.post("/daily-report/send-email")
async def api_send_daily_report_email(request: Request):
    """Send daily report email with host security warning data."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    data = await request.json()
    to_list = data.get("to_list", [])
    cc_list = data.get("cc_list", [])
    subject = data.get("subject", "")
    attach_docx = data.get("attach_docx", False)
    batch_code = data.get("batch_code", "")

    if not to_list:
        raise HTTPException(status_code=400, detail="收件人不能为空")

    from datetime import date
    from pathlib import Path
    from ..services.email_service import send_daily_report_email
    from ..services.spreadsheets import read_table_file

    today = date.today().isoformat()

    # Get the latest or specified result history
    if batch_code:
        result_record = db.get_result_history(batch_code)
    else:
        records, _ = db.list_result_histories(page=1, page_size=1)
        result_record = records[0] if records else None

    if not result_record:
        raise HTTPException(status_code=404, detail="未找到生成记录，请先生成预警报告")

    # Read host data from files
    protection_interrupted = []
    agent_missing = []
    online_unprotected = []

    if result_record.get("protection_interrupted_path"):
        path = Path(result_record["protection_interrupted_path"])
        if path.exists():
            try:
                protection_interrupted = read_table_file(path)
            except Exception:
                pass

    if result_record.get("agent_missing_path"):
        path = Path(result_record["agent_missing_path"])
        if path.exists():
            try:
                agent_missing = read_table_file(path)
            except Exception:
                pass

    if result_record.get("online_unprotected_path"):
        path = Path(result_record["online_unprotected_path"])
        if path.exists():
            try:
                online_unprotected = read_table_file(path)
            except Exception:
                pass

    # Generate DOCX if needed
    docx_path = None
    if attach_docx:
        daily_report = db.get_daily_report_by_date(today)
        if daily_report:
            from ..services.docx_generator import generate_daily_report_docx
            operators = db.list_ops_personnel()
            docx_path = generate_daily_report_docx(daily_report, operators)

    # Get email settings
    email_settings = db.get_email_settings() or {}

    # Build subject if not provided
    if not subject:
        subject = f"安全运营日报 - {today}"

    # Send email
    report_data = {
        "protection_interrupted": protection_interrupted,
        "agent_missing": agent_missing,
        "online_unprotected": online_unprotected,
    }

    result = send_daily_report_email(
        to_list=to_list,
        report_date=today,
        report_data=report_data,
        cc_list=cc_list if cc_list else None,
        docx_path=str(docx_path) if docx_path else None,
        smtp_config=email_settings,
        custom_subject=email_settings.get("daily_report_subject") if email_settings else None,
    )

    return result


@router.post("/email/preview")
async def api_preview_email(request: Request):
    """Preview warning email HTML."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    data = await request.json()
    batch_code = data.get("batch_code", "")

    if not batch_code:
        raise HTTPException(status_code=400, detail="批次号不能为空")

    from pathlib import Path
    from datetime import datetime
    from ..services.email_service import generate_email_from_report
    from ..services.spreadsheets import read_table_file

    # Get current record
    current_record = db.get_result_history(batch_code)
    if not current_record:
        raise HTTPException(status_code=404, detail="未找到该记录")

    # Read host data
    def read_host_data(path_str):
        if not path_str:
            return []
        path = Path(path_str)
        if path.exists():
            try:
                return read_table_file(path)
            except Exception:
                pass
        return []

    current_data = {
        "protection_interrupted": read_host_data(current_record.get("protection_interrupted_path")),
        "agent_missing": read_host_data(current_record.get("agent_missing_path")),
        "online_unprotected": read_host_data(current_record.get("online_unprotected_path")),
    }

    # Find the record closest to 7 days ago for comparison
    week_changes = None
    prev_data = {"protection_interrupted": [], "agent_missing": [], "online_unprotected": []}
    try:
        records, _ = db.list_result_histories(page=1, page_size=100)
        current_time = datetime.fromisoformat(current_record["created_at"].replace("Z", "+00:00")) if "T" in current_record["created_at"] else datetime.strptime(current_record["created_at"][:19], "%Y-%m-%dT%H:%M:%S")

        best_rec = None
        best_diff = float("inf")
        for rec in records:
            if rec["batch_code"] == batch_code:
                continue
            try:
                rec_time = datetime.fromisoformat(rec["created_at"].replace("Z", "+00:00")) if "T" in rec["created_at"] else datetime.strptime(rec["created_at"][:19], "%Y-%m-%dT%H:%M:%S")
                days_diff = abs((current_time - rec_time).days - 7)
                if days_diff < best_diff:
                    best_diff = days_diff
                    best_rec = rec
            except (ValueError, KeyError):
                continue

        if best_rec is not None:
            week_changes = {
                "protection_interrupted": current_record.get("protection_interrupted_count", 0) - best_rec.get("protection_interrupted_count", 0),
                "agent_missing": current_record.get("agent_missing_count", 0) - best_rec.get("agent_missing_count", 0),
                "online_unprotected": current_record.get("online_unprotected_count", 0) - best_rec.get("online_unprotected_count", 0),
            }
            # Read previous week's data
            prev_data = {
                "protection_interrupted": read_host_data(best_rec.get("protection_interrupted_path")),
                "agent_missing": read_host_data(best_rec.get("agent_missing_path")),
                "online_unprotected": read_host_data(best_rec.get("online_unprotected_path")),
            }
    except Exception:
        pass

    # Get report date
    report_date = ""
    # batch_code format: 2026060310344434b197 (first 8 chars are date)
    if len(batch_code) >= 8 and batch_code[:8].isdigit():
        date_part = batch_code[:8]
        report_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"

    # Collect owner emails from the report data
    owner_names = set()
    for data_list in [current_data["protection_interrupted"], current_data["agent_missing"], current_data["online_unprotected"]]:
        for item in data_list:
            name = str(item.get("负责人", "")).strip()
            if name and name not in ("合计", "总计"):
                owner_names.add(name)
    owner_emails_lookup = {}
    if owner_names:
        rows = db.get_owner_emails_by_names(list(owner_names))
        for row in rows:
            owner_emails_lookup[row["owner_name"]] = row["email"]

    html = generate_email_from_report(
        report_date=report_date,
        protection_interrupted=current_data["protection_interrupted"],
        agent_missing=current_data["agent_missing"],
        online_unprotected=current_data["online_unprotected"],
        week_changes=week_changes,
        prev_protection_interrupted=prev_data["protection_interrupted"],
        prev_agent_missing=prev_data["agent_missing"],
        prev_online_unprotected=prev_data["online_unprotected"],
        owner_emails=owner_emails_lookup if owner_emails_lookup else None,
    )

    return {"html": html}


@router.get("/email/report-owners/{batch_code}")
async def api_get_report_owner_emails(request: Request, batch_code: str):
    """Get emails of responsible persons in a report."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    record = db.get_result_history(batch_code)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    from ..services.spreadsheets import read_table_file

    # Collect all unique owner names from the three result files
    owners = set()
    for key in ["protection_interrupted_path", "agent_missing_path", "online_unprotected_path"]:
        path_str = record.get(key)
        if path_str:
            try:
                rows = read_table_file(Path(path_str))
                for row in rows:
                    name = str(row.get("负责人", "")).strip()
                    if name:
                        owners.add(name)
            except Exception:
                pass

    # Look up emails for these owners
    owner_email_rows = db.get_owner_emails_by_names(list(owners))
    emails = [r["email"] for r in owner_email_rows]
    return {"emails": emails, "owners": sorted(owners)}


@router.post("/send-warning-email")
async def api_send_warning_email(request: Request):
    """Send warning email with week-over-week comparison."""
    user = require_login(request)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="未登录")

    data = await request.json()
    to_list = data.get("to_list", [])
    cc_list = data.get("cc_list", [])
    batch_code = data.get("batch_code", "")

    if not to_list:
        raise HTTPException(status_code=400, detail="收件人不能为空")
    if not batch_code:
        raise HTTPException(status_code=400, detail="批次号不能为空")

    from pathlib import Path
    from datetime import datetime
    from ..services.email_service import send_warning_email
    from ..services.spreadsheets import read_table_file

    # Get current record
    current_record = db.get_result_history(batch_code)
    if not current_record:
        raise HTTPException(status_code=404, detail="未找到该记录")

    # Get current data
    def read_host_data(path_str):
        if not path_str:
            return []
        path = Path(path_str)
        if path.exists():
            try:
                return read_table_file(path)
            except Exception:
                pass
        return []

    current_data = {
        "protection_interrupted": read_host_data(current_record.get("protection_interrupted_path")),
        "agent_missing": read_host_data(current_record.get("agent_missing_path")),
        "online_unprotected": read_host_data(current_record.get("online_unprotected_path")),
    }

    # Find the record closest to 7 days ago for comparison
    previous_data = None
    prev_data_files = {"protection_interrupted": [], "agent_missing": [], "online_unprotected": []}
    try:
        records, _ = db.list_result_histories(page=1, page_size=100)
        current_time = datetime.fromisoformat(current_record["created_at"].replace("Z", "+00:00")) if "T" in current_record["created_at"] else datetime.strptime(current_record["created_at"][:19], "%Y-%m-%dT%H:%M:%S")

        best_rec = None
        best_diff = float("inf")
        for rec in records:
            if rec["batch_code"] == batch_code:
                continue
            try:
                rec_time = datetime.fromisoformat(rec["created_at"].replace("Z", "+00:00")) if "T" in rec["created_at"] else datetime.strptime(rec["created_at"][:19], "%Y-%m-%dT%H:%M:%S")
                days_diff = abs((current_time - rec_time).days - 7)
                if days_diff < best_diff:
                    best_diff = days_diff
                    best_rec = rec
            except (ValueError, KeyError):
                continue

        if best_rec is not None:
            previous_data = {
                "protection_interrupted_count": best_rec.get("protection_interrupted_count", 0),
                "agent_missing_count": best_rec.get("agent_missing_count", 0),
                "online_unprotected_count": best_rec.get("online_unprotected_count", 0),
            }
            # Read previous week's data files
            prev_data_files = {
                "protection_interrupted": read_host_data(best_rec.get("protection_interrupted_path")),
                "agent_missing": read_host_data(best_rec.get("agent_missing_path")),
                "online_unprotected": read_host_data(best_rec.get("online_unprotected_path")),
            }
    except Exception:
        pass

    # Get email settings
    email_settings = db.get_email_settings() or {}

    # Get report date from batch_code
    report_date = ""
    if len(batch_code) >= 8 and batch_code[:8].isdigit():
        date_part = batch_code[:8]
        report_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"

    # Build attachments from the three result files (use original filenames)
    attachments = []
    for path_key in ["protection_interrupted_path", "agent_missing_path", "online_unprotected_path"]:
        file_path_str = current_record.get(path_key)
        if file_path_str:
            fp = Path(file_path_str)
            if fp.exists():
                attachments.append({"path": str(fp), "filename": fp.name})

    # Collect owner emails from the report data
    owner_names = set()
    for data_list in [current_data["protection_interrupted"], current_data["agent_missing"], current_data["online_unprotected"]]:
        for item in data_list:
            name = str(item.get("负责人", "")).strip()
            if name and name not in ("合计", "总计"):
                owner_names.add(name)
    owner_emails_lookup = {}
    if owner_names:
        rows = db.get_owner_emails_by_names(list(owner_names))
        for row in rows:
            owner_emails_lookup[row["owner_name"]] = row["email"]

    result = send_warning_email(
        to_list=to_list,
        report_date=report_date,
        current_data=current_data,
        previous_data=previous_data,
        prev_data_files=prev_data_files,
        cc_list=cc_list if cc_list else None,
        smtp_config=email_settings,
        custom_subject=email_settings.get("host_warning_subject") if email_settings else None,
        attachments=attachments if attachments else None,
        owner_emails=owner_emails_lookup if owner_emails_lookup else None,
    )

    return result
