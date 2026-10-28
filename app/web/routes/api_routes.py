from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import select, func, desc

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

router = APIRouter(prefix="/api")

@router.get("/health")
async def api_health() -> Dict[str, Any]:
    """Health check endpoint for web service (Port 20129)."""
    return {
        "status": "healthy",
        "service": "pkl-finder-web",
        "port": 20129,
        "engine": "fastapi"
    }

@router.get("/stats")
async def api_stats() -> Dict[str, Any]:
    """Retrieve platform aggregate statistics."""
    async with async_session_maker() as session:
        total_companies = await session.scalar(select(func.count(Company.id))) or 0
        total_jobs = await session.scalar(select(func.count(Job.id))) or 0
        active_users = await session.scalar(select(func.count(UserWhitelist.id)).where(UserWhitelist.is_active.is_(True))) or 0
        sent_emails = await session.scalar(select(func.count(EmailQueue.id)).where(EmailQueue.status == "sent")) or 0

    return {
        "total_companies": total_companies,
        "total_jobs": total_jobs,
        "active_whitelisted_users": active_users,
        "sent_emails": sent_emails
    }

@router.get("/companies")
async def api_companies(limit: int = 50) -> List[Dict[str, Any]]:
    """List companies via JSON REST API."""
    async with async_session_maker() as session:
        stmt = select(Company).order_by(desc(Company.id)).limit(min(limit, 200))
        res = await session.execute(stmt)
        companies = res.scalars().all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "website": c.website,
                "career_url": c.career_url,
                "recruitment_email": c.recruitment_email,
                "industry": c.industry,
                "is_discovered": c.is_discovered,
                "created_at": c.created_at.isoformat() if c.created_at else None
            }
            for c in companies
        ]

@router.get("/jobs")
async def api_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """List scraped jobs via JSON REST API."""
    async with async_session_maker() as session:
        stmt = select(Job).order_by(desc(Job.id)).limit(min(limit, 200))
        res = await session.execute(stmt)
        jobs = res.scalars().all()
        return [
            {
                "id": j.id,
                "title": j.title,
                "company_name": j.company_name,
                "location": j.location,
                "source": j.source,
                "url": j.url,
                "salary": j.salary,
                "created_at": j.created_at.isoformat() if j.created_at else None
            }
            for j in jobs
        ]

@router.get("/agents")
async def api_agents() -> List[Dict[str, Any]]:
    """Get status telemetry across all multi-agents."""
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
