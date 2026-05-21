from pathlib import Path

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import require_login
from app.db import get_user_by_username, update_user_password
from app.security import verify_password


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.globals["asset_version"] = lambda: str(int((BASE_DIR / "app" / "static" / "app.css").stat().st_mtime))
router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "page_title": "报告管理工具",
            "error_message": "",
            "username": "",
        },
    )


@router.post("/login", response_class=HTMLResponse, response_model=None)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)) -> Response:
    user = get_user_by_username(username.strip())
    if user is None or not verify_password(password, str(user["password_hash"])):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "page_title": "报告管理工具",
                "error_message": "账号或密码错误。",
                "username": username,
            },
            status_code=400,
        )

    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["display_name"] = user["display_name"]
    return RedirectResponse(url="/dashboard", status_code=302)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    return templates.TemplateResponse(
        request=request,
        name="change_password.html",
        context={
            "page_title": "修改密码",
            "current_user": current_user,
            "version_status": {},
            "error_message": "",
            "success_message": "",
        },
    )


@router.post("/change-password", response_class=HTMLResponse, response_model=None)
async def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
) -> Response:
    current_user = require_login(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    user = get_user_by_username(current_user["username"])
    error_message = ""
    success_message = ""

    if user is None or not verify_password(current_password, str(user["password_hash"])):
        error_message = "当前密码错误。"
    elif new_password != confirm_password:
        error_message = "两次输入的新密码不一致。"
    elif len(new_password.strip()) < 6:
        error_message = "新密码长度不能少于 6 位。"
    else:
        update_user_password(current_user["user_id"], new_password)
        success_message = "密码修改成功。"

    return templates.TemplateResponse(
        request=request,
        name="change_password.html",
        context={
            "page_title": "修改密码",
            "current_user": current_user,
            "version_status": {},
            "error_message": error_message,
            "success_message": success_message,
        },
        status_code=400 if error_message else 200,
    )
