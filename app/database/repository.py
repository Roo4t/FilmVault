"""Async repository layer with generic CRUD + model-specific operations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import AppSettings, BatchTask, Base, Metadata, ScrapeLog, VideoFile

T = TypeVar("T", bound=Base)


# ---------------------------------------------------------------------------
# Generic CRUD
# ---------------------------------------------------------------------------

class BaseRepository(Generic[T]):
    """Generic async CRUD repository for a SQLAlchemy model."""

    model: type[T]

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, entity_id: int | str) -> T | None:
        return await self.session.get(self.model, entity_id)

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        stmt = select(self.model).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.model)
        for k, v in filters.items():
            stmt = stmt.where(getattr(self.model, k) == v)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def add(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def add_all(self, entities: list[T]) -> list[T]:
        self.session.add_all(entities)
        await self.session.flush()
        return entities

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)
        await self.session.flush()


# ---------------------------------------------------------------------------
# VideoFile Repository
# ---------------------------------------------------------------------------

class VideoFileRepository(BaseRepository[VideoFile]):
    model = VideoFile

    async def get_by_filepath(self, filepath: str) -> VideoFile | None:
        stmt = select(VideoFile).where(VideoFile.filepath == filepath)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        page: int = 1,
        size: int = 50,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[list[VideoFile], int]:
        """Return paginated video files and total count."""
        stmt = select(VideoFile).options(selectinload(VideoFile.meta))

        if status:
            stmt = stmt.where(VideoFile.status == status)
        if search:
            stmt = stmt.where(VideoFile.filename.ilike(f"%{search}%"))

        # Total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Page
        stmt = stmt.order_by(VideoFile.updated_at.desc()).offset((page - 1) * size).limit(size)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def get_stats(self) -> dict[str, int]:
        """Return aggregate statistics for the dashboard."""
        total = await self.count()
        done = await self.count(status="done")
        failed = await self.count(status="failed")
        pending = total - done - failed
        return {"total": total, "done": done, "failed": failed, "pending": pending}


# ---------------------------------------------------------------------------
# Metadata Repository
# ---------------------------------------------------------------------------

class MetadataRepository(BaseRepository[Metadata]):
    model = Metadata

    async def get_by_video_id(self, video_id: int) -> Metadata | None:
        stmt = select(Metadata).where(Metadata.video_id == video_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, video_id: int, **values: Any) -> Metadata:
        """Insert or update metadata for a video. Returns the metadata record."""
        existing = await self.get_by_video_id(video_id)
        if existing:
            for k, v in values.items():
                setattr(existing, k, v)
            await self.session.flush()
            return existing

        meta = Metadata(video_id=video_id, **values)
        self.session.add(meta)
        await self.session.flush()
        return meta

    async def is_stale(self, video_id: int, ttl_days: int = 7) -> bool:
        """Check if cached metadata is older than ttl_days."""
        meta = await self.get_by_video_id(video_id)
        if meta is None:
            return True
        cutoff = datetime.utcnow() - timedelta(days=ttl_days)
        return meta.updated_at < cutoff  # type: ignore[operator]


# ---------------------------------------------------------------------------
# ScrapeLog Repository
# ---------------------------------------------------------------------------

class ScrapeLogRepository(BaseRepository[ScrapeLog]):
    model = ScrapeLog

    async def get_recent(self, limit: int = 20) -> list[ScrapeLog]:
        stmt = select(ScrapeLog).order_by(ScrapeLog.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def log(
        self,
        video_id: int,
        plugin_name: str,
        status: str,
        error_message: str | None = None,
        source_url: str | None = None,
        duration_ms: int | None = None,
    ) -> ScrapeLog:
        entry = ScrapeLog(
            video_id=video_id,
            plugin_name=plugin_name,
            status=status,
            error_message=error_message,
            source_url=source_url,
            duration_ms=duration_ms,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry


# ---------------------------------------------------------------------------
# BatchTask Repository
# ---------------------------------------------------------------------------

class BatchTaskRepository(BaseRepository[BatchTask]):
    model = BatchTask

    async def get_recent(self, limit: int = 20) -> list[BatchTask]:
        stmt = select(BatchTask).order_by(BatchTask.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_progress(
        self,
        task_id: int,
        completed: int,
        failed: int,
        status: str | None = None,
    ) -> BatchTask | None:
        task = await self.get_by_id(task_id)
        if task is None:
            return None
        task.completed = completed
        task.failed = failed
        if status:
            task.status = status
        await self.session.flush()
        return task


# ---------------------------------------------------------------------------
# AppSettings Repository
# ---------------------------------------------------------------------------

class AppSettingsRepository(BaseRepository[AppSettings]):
    model = AppSettings

    async def get_value(self, key: str, default: str = "") -> str:
        setting = await self.get_by_id(key)
        return setting.value if setting else default

    async def set_value(self, key: str, value: str, type_: str = "str") -> None:
        existing = await self.get_by_id(key)
        if existing:
            existing.value = value
            existing.type = type_
        else:
            self.session.add(AppSettings(key=key, value=value, type=type_))
        await self.session.flush()
