from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import String, Integer, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Company(Base):
    """Company details including discovered properties and career portals (Global)."""
    __tablename__ = "companies"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    website: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    career_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recruitment_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    technologies: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON/comma-separated
    is_discovered: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(50), default="discovered")  # "discovered", "crawled", "blacklisted"
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    # Relationships
    jobs: Mapped[List["Job"]] = relationship("Job", back_populates="company", cascade="all, delete-orphan")
    emails: Mapped[List["EmailQueue"]] = relationship("EmailQueue", back_populates="company", cascade="all, delete-orphan")

class Job(Base):
    """Job vacancy details scraped or crawl-detected (Global)."""
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # Hash of url
    title: Mapped[str] = mapped_column(String(255), index=True)
    company_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    company_name: Mapped[str] = mapped_column(String(255))
    location: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    posted_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    salary: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    work_mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    employment_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    # Relationships
    company: Mapped[Optional[Company]] = relationship("Company", back_populates="jobs")
    ai_scores: Mapped[List["AIScore"]] = relationship(
        "AIScore", back_populates="job", cascade="all, delete-orphan"
    )
    favorites: Mapped[List["Favorite"]] = relationship(
        "Favorite", back_populates="job", cascade="all, delete-orphan"
    )
    history: Mapped[List["History"]] = relationship(
        "History", back_populates="job", cascade="all, delete-orphan"
    )
    emails: Mapped[List["EmailQueue"]] = relationship("EmailQueue", back_populates="job", cascade="all, delete-orphan")

    # Composite index to enforce absolute deduplication of identical roles
    __table_args__ = (
        Index("ix_jobs_unique_title_company_location", "title", "company_name", "location", unique=True),
    )

class AIScore(Base):
    """AI evaluation metadata (User-Specific)."""
    __tablename__ = "ai_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0", index=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"))
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[int] = mapped_column(Integer, index=True)
    reason: Mapped[str] = mapped_column(Text)
    matched_skills: Mapped[str] = mapped_column(Text)
    missing_skills: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    company_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    work_mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    priority: Mapped[Optional[str]] = mapped_column(String(50), default="medium")
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    # Relationships
    job: Mapped[Job] = relationship("Job", back_populates="ai_scores")

    # Composite index to enforce unique matching per user-job pair
    __table_args__ = (
        Index("ix_ai_scores_user_job", "user_id", "job_id", unique=True),
    )

class Favorite(Base):
    """Bookmarks for specific openings (User-Specific)."""
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0", index=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    # Relationships
    job: Mapped[Job] = relationship("Job", back_populates="favorites")

    # Composite index to allow multiple users to favorite the same job
    __table_args__ = (
        Index("ix_favorites_user_job", "user_id", "job_id", unique=True),
    )

class History(Base):
    """System event logging for tracked operations (User-Specific)."""
    __tablename__ = "history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0", index=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(50))
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    # Relationships
    job: Mapped[Job] = relationship("Job", back_populates="history")

class CVProfile(Base):
    """Stores CV text extracted from PDF or Docx uploads (User-Specific)."""
    __tablename__ = "cv_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0", unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    cv_text: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

class Portfolio(Base):
    """Tracks portfolio details, websites, and files (User-Specific)."""
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0", unique=True, index=True)
    github_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    website_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

class CoverLetter(Base):
    """Custom cover letters or text templates (User-Specific)."""
    __tablename__ = "cover_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0", unique=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

class SMTPConfig(Base):
    """Encrypted configurations for mail delivery services (User-Specific)."""
    __tablename__ = "smtp_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0", unique=True, index=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(255))
    password_encrypted: Mapped[str] = mapped_column(Text)
    encryption_type: Mapped[str] = mapped_column(String(50))  # "SSL", "TLS", "None"
    sender_name: Mapped[str] = mapped_column(String(255))
    signature: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class EmailQueue(Base):
    """Stores draft emails waiting for approval (User-Specific)."""
    __tablename__ = "email_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0", index=True)
    job_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id", ondelete="CASCADE"))
    recipient_email: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="draft")  # "draft", "approved", "rejected", "sending", "sent", "failed"
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50))  # "internship", "open_application"
    attachments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list of file paths
    reply_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    company: Mapped[Company] = relationship("Company", back_populates="emails")
    job: Mapped[Optional[Job]] = relationship("Job", back_populates="emails")
