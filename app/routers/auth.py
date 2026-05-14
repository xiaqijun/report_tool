from pathlib import Path

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import get_user_by_username
from app.security import verify_password


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.globals["asset_version"] = str(int((BASE_DIR / "app" / "static" / "app.css").stat().st_mtime))
router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "page_title": "登录",
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
                "page_title": "登录",
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
