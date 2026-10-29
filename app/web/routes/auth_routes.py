import os
from fastapi import APIRouter, Request, Form, Response, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.config.settings import settings
from app.web.security import verify_admin_password, create_admin_session
from app.database.db import async_session_maker
from app.services.google_auth_service import google_auth_service
from app.utils.logger import logger

router = APIRouter()

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Render admin login page."""
    return templates.TemplateResponse(request, "login.html", {"error": None})

@router.post("/admin/login")
async def admin_login_submit(request: Request, password: str = Form(...)):
    """Authenticate admin using password 'uranium235aregoated'."""
    if verify_admin_password(password):
        session_token = create_admin_session()
        response = RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            key="pkl_admin_session",
            value=session_token,
            httponly=True,
            max_age=86400 * 7,
            samesite="lax"
        )
        logger.info("Admin successfully authenticated via web login.")
        return response
    else:
        logger.warning("Failed admin login attempt.")
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Password admin salah. Silakan coba lagi."},
            status_code=401
        )

@router.get("/admin/logout")
async def admin_logout():
    """Clear admin session cookie."""
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("pkl_admin_session")
    return response

@router.get("/auth/google")
async def google_auth_initiate(user_id: int = 0):
    """Initiate Google OAuth2 flow for requesting Gmail Send permission."""
    target_user_id = user_id or settings.TELEGRAM_ADMIN_ID or 1
    auth_url = google_auth_service.get_authorization_url(target_user_id)
    return RedirectResponse(url=auth_url, status_code=status.HTTP_303_SEE_OTHER)

@router.get("/api/auth/google/callback", response_class=HTMLResponse)
@router.get("/auth/google/callback", response_class=HTMLResponse)
async def google_auth_callback(request: Request, code: str = "", state: str = ""):
    """Handle Google OAuth2 callback and store Gmail API credentials."""
    if not code or not state:
        return HTMLResponse("<h3>Error: Missing code or state from Google OAuth</h3>", status_code=400)

    async with async_session_maker() as session:
        success, message, user_id = await google_auth_service.handle_oauth_callback(session, code, state)

    if success:
        user_email = message.split(": ")[-1].split(" ")[0] if ": " in message else "user@gmail.com"
        return templates.TemplateResponse(
            request,
            "google_success.html",
            {"email": user_email, "user_id": user_id}
        )
    else:
        return HTMLResponse(f"<h3>Google SSO Gagal:</h3><p>{message}</p>", status_code=400)
