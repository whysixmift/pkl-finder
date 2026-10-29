import os
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Request, Form, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, or_, desc

from app.web.security import require_admin
from app.database.db import async_session_maker
from app.database.models import Company, Job, EmailQueue, UserWhitelist
from app.agents import (
    scraper_agent,
    discovery_agent,
    cv_agent,
    matching_agent,
    email_drafting_agent,
    email_dispatch_agent,
    access_control_agent,
    scheduler_agent,
)
from app.services import env_service
from app.config.settings import settings
from app.utils.logger import logger

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

def get_all_agents_telemetry() -> List[Dict[str, Any]]:
    """Collect telemetry across all dedicated feature agents."""
    return [
        scraper_agent.get_status(),
        discovery_agent.get_status(),
        cv_agent.get_status(),
        matching_agent.get_status(),
        email_drafting_agent.get_status(),
        email_dispatch_agent.get_status(),
        access_control_agent.get_status(),
        scheduler_agent.get_status(),
    ]

@router.get("", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, msg: Optional[str] = None, err: Optional[str] = None):
    """Executive SaaS dashboard overview."""
    async with async_session_maker() as session:
        # Aggregates
        total_companies = await session.scalar(select(func.count(Company.id))) or 0
        discovered_companies = await session.scalar(select(func.count(Company.id)).where(Company.is_discovered.is_(True))) or 0
        total_jobs = await session.scalar(select(func.count(Job.id))) or 0
        whitelisted_users = await session.scalar(select(func.count(UserWhitelist.id)).where(UserWhitelist.is_active.is_(True))) or 0
        sent_emails = await session.scalar(select(func.count(EmailQueue.id)).where(EmailQueue.status == "sent")) or 0
        draft_emails = await session.scalar(select(func.count(EmailQueue.id)).where(EmailQueue.status == "draft")) or 0

        # Recent 5 companies
        res_comp = await session.execute(select(Company).order_by(desc(Company.id)).limit(5))
        recent_companies = list(res_comp.scalars().all())

        # Recent 5 jobs
        res_jobs = await session.execute(select(Job).order_by(desc(Job.id)).limit(5))
        recent_jobs = list(res_jobs.scalars().all())

    stats = {
        "total_companies": total_companies,
        "discovered_companies": discovered_companies,
        "total_jobs": total_jobs,
        "whitelisted_users": whitelisted_users,
        "sent_emails": sent_emails,
        "draft_emails": draft_emails,
    }

    agents_telemetry = get_all_agents_telemetry()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active_page": "dashboard",
            "stats": stats,
            "agents": agents_telemetry,
            "recent_companies": recent_companies,
            "recent_jobs": recent_jobs,
            "message": msg,
            "error": err,
        }
    )

@router.get("/companies", response_class=HTMLResponse)
async def admin_companies(request: Request, q: Optional[str] = None):
    """Data explorer for all PT (Perusahaan) and scraped jobs."""
    query_str = q.strip() if q else ""
    async with async_session_maker() as session:
        # Fetch companies
        stmt_comp = select(Company).order_by(desc(Company.id))
        if query_str:
            stmt_comp = stmt_comp.where(
                or_(
                    Company.name.ilike(f"%{query_str}%"),
                    Company.industry.ilike(f"%{query_str}%"),
                    Company.recruitment_email.ilike(f"%{query_str}%")
                )
            )
        res_comp = await session.execute(stmt_comp.limit(100))
        companies = list(res_comp.scalars().all())

        # Fetch jobs
        stmt_jobs = select(Job).order_by(desc(Job.id))
        if query_str:
            stmt_jobs = stmt_jobs.where(
                or_(
                    Job.title.ilike(f"%{query_str}%"),
                    Job.company_name.ilike(f"%{query_str}%"),
                    Job.location.ilike(f"%{query_str}%"),
                    Job.source.ilike(f"%{query_str}%")
                )
            )
        res_jobs = await session.execute(stmt_jobs.limit(100))
        jobs = list(res_jobs.scalars().all())

    return templates.TemplateResponse(
        request,
        "companies.html",
        {
            "active_page": "companies",
            "companies": companies,
            "jobs": jobs,
            "search_query": query_str,
        }
    )

@router.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request, msg: Optional[str] = None, err: Optional[str] = None):
    """SaaS Whitelist User Management section."""
    users = await access_control_agent.list_whitelisted_users()
    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "active_page": "users",
            "users": users,
            "message": msg,
            "error": err,
        }
    )

@router.post("/users/add")
async def admin_users_add(identifier: str = Form(...), notes: Optional[str] = Form(None)):
    """Add user to bot whitelist by Telegram Username OR User ID."""
    success, msg, _ = await access_control_agent.add_to_whitelist(identifier, notes)
    if success:
        return RedirectResponse(url=f"/admin/users?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)
    else:
        return RedirectResponse(url=f"/admin/users?err={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/{whitelist_id}/approve")
async def admin_users_approve(whitelist_id: int):
    """Approve a pending or suspended user."""
    success, msg, _ = await access_control_agent.approve_user(whitelist_id)
    return RedirectResponse(url=f"/admin/users?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/{whitelist_id}/reject")
async def admin_users_reject(whitelist_id: int):
    """Reject or suspend a user."""
    success, msg, _ = await access_control_agent.reject_user(whitelist_id)
    return RedirectResponse(url=f"/admin/users?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/{whitelist_id}/toggle")
async def admin_users_toggle(whitelist_id: int):
    """Toggle active/suspended status for whitelisted user."""
    success, msg = await access_control_agent.toggle_status(whitelist_id)
    return RedirectResponse(url=f"/admin/users?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/{whitelist_id}/delete")
async def admin_users_delete(whitelist_id: int):
    """Remove user from whitelist."""
    success, msg = await access_control_agent.remove_from_whitelist(whitelist_id)
    return RedirectResponse(url=f"/admin/users?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/emails", response_class=HTMLResponse)
async def admin_emails(request: Request, msg: Optional[str] = None, err: Optional[str] = None):
    """Monitor email outreach queue and trigger dispatch."""
    async with async_session_maker() as session:
        stmt = select(EmailQueue).order_by(desc(EmailQueue.id)).limit(100)
        res = await session.execute(stmt)
        emails = list(res.scalars().all())

    return templates.TemplateResponse(
        request,
        "emails.html",
        {
            "active_page": "emails",
            "emails": emails,
            "message": msg,
            "error": err,
        }
    )

@router.post("/emails/{email_id}/send")
async def admin_email_send(email_id: int):
    """Dispatch single email via Google Gmail API or SMTP."""
    success, msg = await email_dispatch_agent.dispatch_single(email_id)
    if success:
        return RedirectResponse(url=f"/admin/emails?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)
    else:
        return RedirectResponse(url=f"/admin/emails?err={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/emails/dispatch-all")
async def admin_email_dispatch_all():
    """Dispatch all approved drafts in queue."""
    res = await email_dispatch_agent.dispatch_approved_queue()
    msg = f"Berhasil mengirim {res.get('sent', 0)} email. Gagal: {res.get('failed', 0)}."
    return RedirectResponse(url=f"/admin/emails?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/agents", response_class=HTMLResponse)
async def admin_agents(request: Request):
    """Dedicated telemetry and status monitor for all multi-agents."""
    agents_telemetry = get_all_agents_telemetry()
    return templates.TemplateResponse(
        request,
        "agents.html",
        {
            "active_page": "agents",
            "agents": agents_telemetry,
        }
    )

@router.post("/trigger-scrape")
async def admin_trigger_scrape():
    """On-demand trigger for scraper agent."""
    new_jobs = await scraper_agent.run()
    msg = f"Scraping selesai! {len(new_jobs)} lowongan baru tersimpan ke database."
    return RedirectResponse(url=f"/admin/dashboard?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/trigger-crawl")
async def admin_trigger_crawl():
    """On-demand trigger for company discovery agent."""
    res = await discovery_agent.run()
    msg = f"Crawl selesai! Perusahaan terdeteksi: {res.get('discovered_companies', 0)}."
    return RedirectResponse(url=f"/admin/dashboard?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/settings", response_class=HTMLResponse)
async def admin_settings_page(request: Request, msg: Optional[str] = None, err: Optional[str] = None):
    """Admin configuration dashboard for editing .env variables."""
    raw_content = env_service.read_env_content()
    env_dict = env_service.get_env_dict()

    current_values = {
        "TELEGRAM_BOT_TOKEN": env_dict.get("TELEGRAM_BOT_TOKEN", settings.TELEGRAM_BOT_TOKEN),
        "ADMIN_BOT_TOKEN": env_dict.get("ADMIN_BOT_TOKEN", settings.ADMIN_BOT_TOKEN),
        "TELEGRAM_ADMIN_ID": env_dict.get("TELEGRAM_ADMIN_ID", str(settings.TELEGRAM_ADMIN_ID)),
        "OPENROUTER_API_KEY": env_dict.get("OPENROUTER_API_KEY", settings.OPENROUTER_API_KEY),
        "PRIMARY_MODEL": env_dict.get("PRIMARY_MODEL", settings.PRIMARY_MODEL),
        "FALLBACK_MODELS": env_dict.get("FALLBACK_MODELS", settings.FALLBACK_MODELS),
        "OPENROUTER_API_URL": env_dict.get("OPENROUTER_API_URL", settings.OPENROUTER_API_URL),
        "GOOGLE_CLIENT_ID": env_dict.get("GOOGLE_CLIENT_ID", settings.GOOGLE_CLIENT_ID),
        "GOOGLE_CLIENT_SECRET": env_dict.get("GOOGLE_CLIENT_SECRET", settings.GOOGLE_CLIENT_SECRET),
        "GOOGLE_REDIRECT_URI": env_dict.get("GOOGLE_REDIRECT_URI", settings.GOOGLE_REDIRECT_URI),
        "ADMIN_PASSWORD": env_dict.get("ADMIN_PASSWORD", settings.ADMIN_PASSWORD),
        "BOT_PORT": env_dict.get("BOT_PORT", str(settings.BOT_PORT)),
        "WEB_PORT": env_dict.get("WEB_PORT", str(settings.WEB_PORT)),
        "HOST": env_dict.get("HOST", settings.HOST),
        "WEB_BASE_URL": env_dict.get("WEB_BASE_URL", settings.WEB_BASE_URL),
        "DATABASE_URL": env_dict.get("DATABASE_URL", settings.DATABASE_URL),
        "CHECK_INTERVAL_MINUTES": env_dict.get("CHECK_INTERVAL_MINUTES", str(settings.CHECK_INTERVAL_MINUTES)),
        "MAX_JOBS_PER_RUN": env_dict.get("MAX_JOBS_PER_RUN", str(settings.MAX_JOBS_PER_RUN)),
        "SCORE_THRESHOLD": env_dict.get("SCORE_THRESHOLD", str(settings.SCORE_THRESHOLD)),
        "SEARCH_KEYWORDS": env_dict.get("SEARCH_KEYWORDS", settings.SEARCH_KEYWORDS),
        "SEARCH_LOCATIONS": env_dict.get("SEARCH_LOCATIONS", settings.SEARCH_LOCATIONS),
    }

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active_page": "settings",
            "env_dict": current_values,
            "raw_content": raw_content,
            "env_path": env_service.get_env_file_path(),
            "message": msg,
            "error": err,
        }
    )


@router.post("/settings/form")
async def admin_save_settings_form(
    telegram_bot_token: str = Form(...),
    admin_bot_token: str = Form(""),
    telegram_admin_id: str = Form(...),
    openrouter_api_key: str = Form(...),
    primary_model: str = Form("google/gemma-4-31b-it:free"),
    fallback_models: str = Form("qwen/qwen-2.5-72b-instruct:free,deepseek/deepseek-chat:free"),
    openrouter_api_url: str = Form("https://openrouter.ai/api/v1/chat/completions"),
    google_client_id: str = Form(""),
    google_client_secret: str = Form(""),
    google_redirect_uri: str = Form(""),
    admin_password: str = Form("uranium235aregoated"),
    bot_port: str = Form("20128"),
    web_port: str = Form("20129"),
    host: str = Form("0.0.0.0"),
    web_base_url: str = Form("http://localhost:20129"),
    database_url: str = Form("sqlite+aiosqlite:///data/jobs.db"),
    check_interval_minutes: str = Form("60"),
    max_jobs_per_run: str = Form("20"),
    score_threshold: str = Form("70"),
    search_keywords: str = Form(""),
    search_locations: str = Form(""),
):
    """Save structured settings form directly into .env."""
    updates = {
        "TELEGRAM_BOT_TOKEN": telegram_bot_token.strip(),
        "ADMIN_BOT_TOKEN": admin_bot_token.strip(),
        "TELEGRAM_ADMIN_ID": telegram_admin_id.strip(),
        "OPENROUTER_API_KEY": openrouter_api_key.strip(),
        "PRIMARY_MODEL": primary_model.strip(),
        "FALLBACK_MODELS": fallback_models.strip(),
        "OPENROUTER_API_URL": openrouter_api_url.strip(),
        "GOOGLE_CLIENT_ID": google_client_id.strip(),
        "GOOGLE_CLIENT_SECRET": google_client_secret.strip(),
        "GOOGLE_REDIRECT_URI": google_redirect_uri.strip(),
        "ADMIN_PASSWORD": admin_password.strip(),
        "BOT_PORT": bot_port.strip(),
        "WEB_PORT": web_port.strip(),
        "HOST": host.strip(),
        "WEB_BASE_URL": web_base_url.strip(),
        "DATABASE_URL": database_url.strip(),
        "CHECK_INTERVAL_MINUTES": check_interval_minutes.strip(),
        "MAX_JOBS_PER_RUN": max_jobs_per_run.strip(),
        "SCORE_THRESHOLD": score_threshold.strip(),
        "SEARCH_KEYWORDS": search_keywords.strip(),
        "SEARCH_LOCATIONS": search_locations.strip(),
    }
    ok = env_service.save_env_dict(updates)
    if ok:
        return RedirectResponse(
            url="/admin/settings?msg=Konfigurasi .env berhasil disimpan dan langsung dimuat ke sistem!",
            status_code=status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse(
        url="/admin/settings?err=Gagal menyimpan konfigurasi .env!",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/settings/raw")
async def admin_save_settings_raw(raw_env_content: str = Form(...)):
    """Save raw text directly to .env."""
    ok = env_service.save_raw_env(raw_env_content)
    if ok:
        return RedirectResponse(
            url="/admin/settings?msg=File .env berhasil diperbarui dari editor teks mentah dan dimuat ke sistem!",
            status_code=status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse(
        url="/admin/settings?err=Gagal memperbarui file .env!",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/settings/reset")
async def admin_reset_settings():
    """Reset .env to .env.example defaults."""
    ok = env_service.reset_to_example()
    if ok:
        return RedirectResponse(
            url="/admin/settings?msg=File .env berhasil di-reset ke template awal (.env.example)!",
            status_code=status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse(
        url="/admin/settings?err=Gagal me-reset file .env!",
        status_code=status.HTTP_303_SEE_OTHER
    )
