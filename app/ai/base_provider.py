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
    async def write_cold_email(self, company_name: str, cv_text: str) -> Tuple[str, str]:
        """Generate a personalized cover application email from CV."""
        pass
