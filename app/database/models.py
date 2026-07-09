from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import String, Integer, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Company(Base):
    """Company information."""
    __tablename__ = "companies"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Relationships
    jobs: Mapped[List["Job"]] = relationship("Job", back_populates="company")

class Job(Base):
    """Job vacancy information."""
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_key: Mapped[str] = mapped_column(String(64), unique=True, index=True) # Hash of url or unique source ID
    title: Mapped[str] = mapped_column(String(255), index=True)
    company_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("companies.id"), nullable=True)
    company_name: Mapped[str] = mapped_column(String(255)) # Denormalized for convenience
    location: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    posted_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(50), index=True) # glints, linkedin, indeed, etc.
    salary: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    work_mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True) # Remote, Hybrid, On-site
    employment_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True) # Internship, Full-time, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Relationships
    company: Mapped[Optional[Company]] = relationship("Company", back_populates="jobs")
    ai_score: Mapped[Optional["AIScore"]] = relationship(
        "AIScore", back_populates="job", cascade="all, delete-orphan", uselist=False
    )
    favorites: Mapped[List["Favorite"]] = relationship(
        "Favorite", back_populates="job", cascade="all, delete-orphan"
    )
    history: Mapped[List["History"]] = relationship(
        "History", back_populates="job", cascade="all, delete-orphan"
    )

class AIScore(Base):
    """AI evaluation score and feedback."""
    __tablename__ = "ai_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[int] = mapped_column(Integer, index=True)
    reason: Mapped[str] = mapped_column(Text) # JSON serialized list of reasons
    matched_skills: Mapped[str] = mapped_column(Text) # JSON serialized list of matched skills
    missing_skills: Mapped[str] = mapped_column(Text) # JSON serialized list of missing skills
    summary: Mapped[str] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="ai_score")

class Favorite(Base):
    """User marked favorite jobs."""
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="favorites")

class History(Base):
    """Log of actions/messages sent for jobs."""
    __tablename__ = "history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(50)) # "scraped", "evaluated", "sent_telegram", "skipped"
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="history")
