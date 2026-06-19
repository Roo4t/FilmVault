"""Directory scanning service — discovers video files and imports them into the DB."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config
from app.database.models import BatchTask, ScrapeLog, VideoFile
from app.database.repository import VideoFileRepository
from app.parser.engine import FilenameParser

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".m4v", ".ts", ".m2ts", ".webm"}


class ScanService:
    """Scans configured directories for video files and adds them to the library."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.parser = FilenameParser()

    async def scan(self, directories: list[str] | None = None) -> dict[str, int]:
        """Scan directories and import discovered videos.

        Returns a dict with counts: {added, updated, skipped, total}.
        """
        dirs = directories or config.video_directories
        if not dirs:
            logger.warning("未配置视频目录，扫描跳过")
            return {"added": 0, "updated": 0, "skipped": 0, "total": 0}

        logger.info(f"开始扫描目录: {dirs}")

        # Create a batch task record
        task = BatchTask(task_type="scan", status="running", total=0, completed=0)
        self.session.add(task)
        await self.session.flush()

        repo = VideoFileRepository(self.session)
        added = updated = skipped = 0
        all_files: list[Path] = []

        # Collect files
        for d in dirs:
            if not os.path.isdir(d):
                logger.warning(f"目录不存在，跳过: {d}")
                continue
            for root, _, files in os.walk(d):
                for name in files:
                    if Path(name).suffix.lower() in VIDEO_EXTENSIONS:
                        all_files.append(Path(root) / name)

        total = len(all_files)
        task.total = total
        await self.session.flush()
        logger.info(f"发现 {total} 个视频文件")

        # Process each file
        for i, filepath in enumerate(all_files):
            filename = filepath.name
            try:
                # Check if already exists
                existing = await repo.get_by_filepath(str(filepath))
                parse_result = self.parser.parse(filename)
                parsed_code = parse_result.code if parse_result.code else None

                if existing:
                    # Update parsed code if improved
                    if parsed_code and not existing.parsed_code:
                        existing.parsed_code = parsed_code
                        existing.parsed_confidence = parse_result.confidence
                        existing.matched_pattern = parse_result.matched_pattern
                        updated += 1
                    else:
                        skipped += 1
                else:
                    video = VideoFile(
                        filename=filename,
                        filepath=str(filepath),
                        parsed_code=parsed_code,
                        parsed_confidence=parse_result.confidence,
                        matched_pattern=parse_result.matched_pattern,
                        file_size=filepath.stat().st_size,
                        status="pending",
                    )
                    self.session.add(video)
                    added += 1

                task.completed = i + 1
                if (i + 1) % 50 == 0:
                    await self.session.flush()

            except Exception:
                logger.exception(f"处理文件失败: {filename}")

        task.status = "completed"
        log = ScrapeLog(
            video_id=None,
            plugin_name="scan",
            status="completed",
            error_message=f"扫描完成: 新增 {added}, 更新 {updated}, 跳过 {skipped}, 总计 {total}",
        )
        self.session.add(log)
        await self.session.commit()

        logger.info(f"扫描完成 — 新增 {added} | 更新 {updated} | 跳过 {skipped} | 总计 {total}")
        return {"added": added, "updated": updated, "skipped": skipped, "total": total}
