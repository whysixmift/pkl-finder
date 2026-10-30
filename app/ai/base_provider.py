from abc import ABC, abstractmethod
from typing import Optional, List, Tuple
from pydantic import BaseModel, Field

class AIResult(BaseModel):
    recommended: bool = Field(default=False)
    score: int = Field(default=0, ge=0, le=100)
    reason: List[str] = Field(default_factory=list)
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    summary: str = Field(default="")
    company_category: Optional[str] = Field(default="Technology")
    work_mode: Optional[str] = Field(default="On-site")
    priority: Optional[str] = Field(default="medium")

class BaseLLMProvider(ABC):
    """Abstract base class for all AI/LLM matching and email writer providers."""

    @abstractmethod
    async def verify_connectivity(self) -> Tuple[bool, str, int]:
        """Verify provider credentials, connection status, latency, and models configuration on startup.
        Returns:
            Tuple[success: bool, status_message: str, latency_ms: int]
        """
        pass

    @abstractmethod
    async def evaluate_job(
        self, title: str, company: str, location: str, description: str, cv_text: Optional[str] = None
    ) -> AIResult:
        """Analyze a job posting suitability score against CV context."""
        pass

    @abstractmethod
    async def write_cold_email(
        self,
        company_name: str,
        cv_text: str,
        job_title: Optional[str] = None,
        job_description: Optional[str] = None
    ) -> Tuple[str, str]:
        """Generate a personalized cover application email tailored to CV and company."""
        pass

    async def analyze_cv_intelligence(self, cv_text: str) -> dict:
        """Analyze candidate CV to detect suitable job roles, top skills, and scraper search queries."""
        return {}

    async def generate_code_patch(
        self,
        bug_report: str,
        log_context: str,
        code_context: str,
        file_hint: Optional[str] = None
    ) -> dict:
        """Analyze bug report and code context, returning a surgical code fix dictionary."""
        return {}

    async def prepare_interview_cheatsheet(
        self,
        title: Optional[str] = None,
        company: Optional[str] = None,
        description: Optional[str] = None,
        cv_text: Optional[str] = None,
        **kwargs
    ) -> dict:
        """Generate tailored technical questions, behavioral questions, and tips for this job opening."""
        return {}

    async def optimize_cv_for_job(
        self,
        title: Optional[str] = None,
        company: Optional[str] = None,
        description: Optional[str] = None,
        cv_text: Optional[str] = None,
        **kwargs
    ) -> dict:
        """Generate tailored ATS-friendly profile summary and achievement bullet points."""
        return {}

    async def recommend_portfolio_project(
        self,
        title: Optional[str] = None,
        company: Optional[str] = None,
        missing_skills: Optional[List[str]] = None,
        cv_text: Optional[str] = None,
        **kwargs
    ) -> dict:
        """Recommend a practical 2-3 day weekend project to close skill gaps for this job opening."""
        return {}

    async def draft_followup_email(
        self,
        company_name: Optional[str] = None,
        job_title: Optional[str] = None,
        cv_text: Optional[str] = None,
        candidate_name: Optional[str] = None,
        **kwargs
    ) -> dict:
        """Generate polite, professional follow-up email after applying."""
        return {}
