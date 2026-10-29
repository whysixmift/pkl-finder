import json
import pytest
from app.ai.evaluator import evaluator
from app.agents.access_control_agent import access_control_agent
from app.database.db import async_session_maker, init_db
from app.database.models import UserWhitelist, CVProfile

@pytest.mark.asyncio
async def test_cv_intelligence_heuristic_fallback():
    """Test heuristic analysis of candidate CV."""
    sample_cv = (
        "Julian Mifta - Software Engineer. Proficient in Python, FastAPI, Docker, PostgreSQL, "
        "IoT, ESP32, Robotics, and Linux systems. Built REST APIs and automated scraping tools."
    )
    intel = evaluator._fallback_analyze_cv(sample_cv)
    assert "recommended_roles" in intel
    assert "top_skills" in intel
    assert "search_keywords" in intel
    assert len(intel["recommended_roles"]) > 0
    assert any("python" in role.lower() or "backend" in role.lower() for role in intel["recommended_roles"])
    assert any("python" in kw.lower() or "backend" in kw.lower() for kw in intel["search_keywords"])

@pytest.mark.asyncio
async def test_access_control_approval_workflow():
    """Test pending registration, approval, and rejection cycle."""
    await init_db()
    test_user_id = 9988776655
    test_username = "candidate_newbie"

    # 1. Register as pending
    user_rec, is_new = await access_control_agent.get_or_create_pending_user(
        user_id=test_user_id,
        username=test_username,
        source="telegram"
    )
    assert user_rec is not None
    assert user_rec.status == "pending"
    assert user_rec.is_active is False

    # Verify user is blocked while pending
    allowed_before = await access_control_agent.is_allowed(test_user_id, test_username)
    assert allowed_before is False

    # 2. Approve user
    success, msg, uid = await access_control_agent.approve_user(test_user_id)
    assert success is True
    assert uid == test_user_id

    # Verify user is now permitted
    allowed_after = await access_control_agent.is_allowed(test_user_id, test_username)
    assert allowed_after is True

    # 3. Reject user
    rej_success, rej_msg, rej_uid = await access_control_agent.reject_user(test_user_id)
    assert rej_success is True
    allowed_rejected = await access_control_agent.is_allowed(test_user_id, test_username)
    assert allowed_rejected is False

    # Cleanup
    async with async_session_maker() as session:
        u = await session.get(UserWhitelist, user_rec.id)
        if u:
            await session.delete(u)
            await session.commit()

@pytest.mark.asyncio
async def test_career_evaluator_supports_full_time_jobs():
    """Test that evaluator no longer automatically penalizes non-internship full-time roles."""
    sample_cv = "Senior Python Backend Developer with 4 years experience in FastAPI, Docker, and Microservices."
    res = evaluator._fallback_evaluate(
        title="Junior Python Backend Engineer",
        company="Tech Innovate",
        location="Jakarta, Remote",
        description="Looking for Python developers with experience in REST APIs and Docker."
    )
    # Under the updated logic, technical skill matches should produce high score
    assert res.score >= 50
    assert any("Python" in s or "Backend" in s for s in res.matched_skills)
