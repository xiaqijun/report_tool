from fastapi import Request
from fastapi.responses import RedirectResponse


def get_session_user(request: Request) -> dict[str, str] | None:
    user_id = request.session.get("user_id")
    username = request.session.get("username")
    display_name = request.session.get("display_name")
    if not user_id or not username:
        return None
    return {
        "user_id": str(user_id),
        "username": str(username),
        "display_name": str(display_name or username),
    }


def require_login(request: Request) -> dict[str, str] | RedirectResponse:
    user = get_session_user(request)
    if user is not None:
        return user
    return RedirectResponse(url="/login", status_code=302)
