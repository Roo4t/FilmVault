"""SQLAlchemy async engine and session factory."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import config

logger = logging.getLogger(__name__)

engine = create_async_engine(
    config.database_url,
    echo=False,
    future=True,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def init_db_sync() -> None:
    """Synchronous DB init — creates tables using sqlite3 directly.
    
    Called before the async event loop starts, ensuring tables exist
    before any page queries the database.
    """
    import sqlite3
    from pathlib import Path

    # Extract path from sqlite+aiosqlite:///...
    db_url = config.database_url
    if db_url.startswith("sqlite+aiosqlite:///"):
        db_path = db_url[len("sqlite+aiosqlite:///"):]
    elif db_url.startswith("sqlite:///"):
        db_path = db_url[len("sqlite:///"):]
    else:
        logger.warning("Cannot parse database URL for sync init: %s", db_url)
        return

    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(db_file))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS video_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filepath VARCHAR(1024) UNIQUE NOT NULL,
                filename VARCHAR(512) NOT NULL,
                file_size INTEGER DEFAULT 0,
                file_mtime FLOAT DEFAULT 0.0,
                parsed_code VARCHAR(128),
                parsed_confidence FLOAT DEFAULT 0.0,
                matched_pattern VARCHAR(64),
                status VARCHAR(32) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_video_files_filepath ON video_files(filepath)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_video_files_filename ON video_files(filename)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_video_files_parsed_code ON video_files(parsed_code)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER UNIQUE NOT NULL
                    REFERENCES video_files(id) ON DELETE CASCADE,
                title VARCHAR(512) DEFAULT '',
                original_title VARCHAR(512),
                plot TEXT,
                poster_url VARCHAR(2048),
                fanart_urls JSON DEFAULT '[]',
                year INTEGER,
                premiered VARCHAR(16),
                runtime INTEGER,
                genres JSON DEFAULT '[]',
                tags JSON DEFAULT '[]',
                actors JSON DEFAULT '[]',
                director VARCHAR(256),
                studio VARCHAR(256),
                rating FLOAT,
                source_plugin VARCHAR(64) DEFAULT '',
                source_url VARCHAR(2048),
                raw_data JSON DEFAULT '{}',
                nfo_generated BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_metadata_video_id ON metadata(video_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS scrape_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER
                    REFERENCES video_files(id) ON DELETE CASCADE,
                plugin_name VARCHAR(64),
                status VARCHAR(32),
                error_message TEXT,
                source_url VARCHAR(2048),
                duration_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_scrape_logs_video_id ON scrape_logs(video_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type VARCHAR(32),
                status VARCHAR(32) DEFAULT 'pending',
                total INTEGER DEFAULT 0,
                completed INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                result_summary JSON DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key VARCHAR(128) PRIMARY KEY,
                value TEXT DEFAULT '',
                type VARCHAR(32) DEFAULT 'str',
                description VARCHAR(512),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()
        logger.info("Database tables initialized successfully")
    except Exception as exc:
        logger.exception("Failed to initialize database tables: %s", exc)


async def get_session() -> AsyncSession:
    """Yield an async database session (for FastAPI dependency injection)."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables if they don't exist."""
    from app.database.models import Base  # noqa: PLC0415 — deferred to avoid circular imports

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
