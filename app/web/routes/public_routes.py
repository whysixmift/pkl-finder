import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@router.get("/", response_class=HTMLResponse)
@router.head("/", response_class=HTMLResponse)
async def public_landing(request: Request):
    """Public SaaS landing page."""
    return templates.TemplateResponse(request, "landing.html", {})
