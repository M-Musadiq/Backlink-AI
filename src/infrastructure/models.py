from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from src.infrastructure.database import Base


class TrackedURL(Base):
    __tablename__ = "tracked_urls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(2048), unique=True, nullable=False, index=True)
    domain = Column(String(255), nullable=False, index=True)
    title = Column(String(500), default="")
    source = Column(String(50), default="")
    status = Column(String(50), default="discovered", index=True)
    discovered_at = Column(DateTime, default=datetime.utcnow)
    last_checked = Column(DateTime, nullable=True)

    prospects = relationship("Prospect", back_populates="tracked_url")


class PlatformConfigDB(Base):
    __tablename__ = "platform_config"

    domain = Column(String(255), primary_key=True)
    scraper_type = Column(String(50), default="static")
    post_method = Column(String(50), default="not_supported")
    requires_auth = Column(Boolean, default=False)
    rate_limit_seconds = Column(Integer, default=5)
    guidelines_url = Column(String(2048), default="")
    last_updated = Column(DateTime, default=datetime.utcnow)


class GuidelinesCache(Base):
    __tablename__ = "guidelines_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain = Column(String(255), nullable=False, index=True)
    content = Column(Text, nullable=False)
    scraped_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    scraper_type_used = Column(String(50), default="")


class Prospect(Base):
    __tablename__ = "prospects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracked_url_id = Column(Integer, ForeignKey("tracked_urls.id"), nullable=True)
    url = Column(String(2048), nullable=False)
    domain = Column(String(255), nullable=False, index=True)
    title = Column(String(500), default="")
    body_preview = Column(Text, default="")
    relevance_score = Column(Float, default=0.0)
    status = Column(String(50), default="discovered", index=True)
    draft_content = Column(Text, default="")
    posted_url = Column(String(2048), default="")
    platform_post_id = Column(String(255), default="")
    posted_at = Column(DateTime, nullable=True)
    post_error = Column(Text, default="")
    feedback_notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tracked_url = relationship("TrackedURL", back_populates="prospects")
    audit_logs = relationship("AuditLog", back_populates="prospect")


class PlatformSession(Base):
    __tablename__ = "platform_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    session_data_encrypted = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    last_used = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prospect_id = Column(Integer, ForeignKey("prospects.id"), nullable=True)
    action = Column(String(100), nullable=False)
    details = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    prospect = relationship("Prospect", back_populates="audit_logs")
