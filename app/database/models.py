"""SQLAlchemy ORM models for FilmVault."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# ---------------------------------------------------------------------------
# VideoFile — scanned video file record
# ---------------------------------------------------------------------------

class VideoFile(Base):
    """Represents a video file discovered during directory scanning."""

    __tablename__ = "video_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filepath: Mapped[str] = mapped_column(String(1024), unique=True, index=True, comment="Absolute file path")
    filename: Mapped[str] = mapped_column(String(512), index=True, comment="Base filename with extension")
    file_size: Mapped[int] = mapped_column(Integer, default=0, comment="File size in bytes")
    file_mtime: Mapped[float] = mapped_column(Float, default=0.0, comment="Last modified timestamp")

    # Parsed fields
    parsed_code: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True, comment="Parsed identifier code")
    parsed_confidence: Mapped[float] = mapped_column(Float, default=0.0, comment="Parse confidence 0-1")
    matched_pattern: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="Matched regex pattern name")

    # Status
    status: Mapped[str] = mapped_column(String(32), default="pending", comment="pending|scraping|done|failed")

    # Relationships
    meta: Mapped[Metadata | None] = relationship("Metadata", back_populates="video", uselist=False, cascade="all, delete-orphan")
    scrape_logs: Mapped[list[ScrapeLog]] = relationship("ScrapeLog", back_populates="video", cascade="all, delete-orphan")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<VideoFile(id={self.id}, filename='{self.filename}', status='{self.status}')>"


# ---------------------------------------------------------------------------
# Metadata — scraped metadata for a video file
# ---------------------------------------------------------------------------

class Metadata(Base):
    """Scraped metadata linked 1:1 with a video file."""

    __tablename__ = "metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("video_files.id", ondelete="CASCADE"), unique=True, index=True)

    # Core fields
    title: Mapped[str] = mapped_column(String(512), default="", comment="Display title")
    original_title: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="Original language title")
    plot: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Plot summary")
    poster_url: Mapped[str | None] = mapped_column(String(2048), nullable=True, comment="Poster image URL")
    fanart_urls: Mapped[list[str]] = mapped_column(JSON, default=list, comment="Fanart/backdrop URLs")

    # Temporal
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    premiered: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="YYYY-MM-DD")
    runtime: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Duration in minutes")

    # Classification
    genres: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    actors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, comment="[{name, role?, thumb?}]")
    director: Mapped[str | None] = mapped_column(String(256), nullable=True)
    studio: Mapped[str | None] = mapped_column(String(256), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Source tracking
    source_plugin: Mapped[str] = mapped_column(String(64), default="")
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, comment="Raw scraper response")

    # NFO
    nfo_generated: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationship
    video: Mapped[VideoFile] = relationship("VideoFile", back_populates="meta")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Metadata(video_id={self.video_id}, title='{self.title}')>"


# ---------------------------------------------------------------------------
# ScrapeLog — audit trail for scraping attempts
# ---------------------------------------------------------------------------

class ScrapeLog(Base):
    """Records each scraping attempt for auditing and debugging."""

    __tablename__ = "scrape_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("video_files.id", ondelete="CASCADE"), index=True, nullable=True)

    plugin_name: Mapped[str] = mapped_column(String(64), comment="Scraper plugin that was used")
    status: Mapped[str] = mapped_column(String(32), comment="success|failed")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Scraping duration in ms")

    # Relationship
    video: Mapped[VideoFile] = relationship("VideoFile", back_populates="scrape_logs")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<ScrapeLog(video_id={self.video_id}, plugin='{self.plugin_name}', status='{self.status}')>"


# ---------------------------------------------------------------------------
# BatchTask — tracks long-running operations
# ---------------------------------------------------------------------------

class BatchTask(Base):
    """Tracks the progress of batch operations (scan / scrape / export)."""

    __tablename__ = "batch_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(32), comment="scan|scrape|export")
    status: Mapped[str] = mapped_column(String(32), default="pending", comment="pending|running|completed|failed")
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<BatchTask(id='{self.id}', type='{self.task_type}', status='{self.status}')>"


# ---------------------------------------------------------------------------
# AppSettings — key-value configuration store
# ---------------------------------------------------------------------------

class AppSettings(Base):
    """Persistent application settings (overrides config.py defaults)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(32), default="str", comment="str|int|bool|json")
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<AppSettings(key='{self.key}', value='{self.value[:30]}...')>"
