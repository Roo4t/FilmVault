"""NFO file writer — writes .nfo files alongside video files (atomic write)."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class NFOWriter:
    """
    Writes Kodi-compatible .nfo files with atomic write.

    Files are stored in a ``metadata/`` subdirectory alongside the video to keep
    the video directory clean::

        VideoDir/
        ├── STARS-251.mp4
        ├── START-315.mp4
        └── metadata/
            ├── STARS-251.nfo
            ├── STARS-251-poster.jpg
            ├── START-315.nfo
            └── START-315-poster.jpg

    **Atomic write**: content is written to a temporary file first, then
    the temp file is renamed to the target path via ``os.replace``. This
    ensures the target file is never left in a partial/corrupt state,
    even if the process crashes mid-write.
    """

    META_SUBDIR = "metadata"

    @classmethod
    def resolve_nfo_path(cls, video_path: str | Path, output_dir: str | Path | None = None) -> Path:
        """
        Determine the .nfo file path for a given video.

        Default: stores in ``{video_dir}/metadata/{video_stem}.nfo``.

        Args:
            video_path: Absolute path to the video file.
            output_dir: If provided, override the metadata subdirectory.

        Returns:
            Absolute .nfo file path.
        """
        vp = Path(video_path)
        if output_dir:
            od = Path(output_dir)
            od.mkdir(parents=True, exist_ok=True)
            return od / f"{vp.stem}.nfo"
        meta_dir = vp.parent / cls.META_SUBDIR
        meta_dir.mkdir(parents=True, exist_ok=True)
        return meta_dir / f"{vp.stem}.nfo"

    @staticmethod
    def write(video_path: str | Path, nfo_content: str, output_dir: str | Path | None = None) -> Path:
        """
        Write a single .nfo file (atomic).

        The content is written to a temporary file in the same directory,
        then atomically renamed to the target ``.nfo`` path. This prevents
        partial/corrupt files on crash or power loss.

        Args:
            video_path: Path to the video file.
            nfo_content: NFO XML content as a string.
            output_dir: Optional alternative output directory.

        Returns:
            Path to the written .nfo file.
        """
        nfo_path = NFOWriter.resolve_nfo_path(video_path, output_dir)
        nfo_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temp file in the same directory (same fs = rename is atomic)
        tmp: str | None = None
        try:
            fd, tmp = tempfile.mkstemp(
                suffix=".nfo.tmp",
                prefix=f"._{nfo_path.stem}_",
                dir=str(nfo_path.parent),
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(nfo_content)

            # os.replace is atomic on POSIX; on Windows it uses MoveFileEx
            # with MOVEFILE_REPLACE_EXISTING which is near-atomic
            os.replace(tmp, str(nfo_path))
            logger.debug("Wrote NFO: %s", nfo_path)
            return nfo_path

        except OSError as exc:
            logger.error("Failed to write NFO for %s: %s", nfo_path, exc)
            raise
        finally:
            # Clean up temp file if something went wrong
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    @classmethod
    def write_all(
        cls,
        pairs: list[tuple[str, str]],
        output_dir: str | Path | None = None,
    ) -> int:
        """
        Write multiple .nfo files (atomic).

        Args:
            pairs: List of (video_path, nfo_content) tuples.
            output_dir: Optional alternative output directory.

        Returns:
            Number of files successfully written.
        """
        count = 0
        for video_path, content in pairs:
            try:
                cls.write(video_path, content, output_dir)
                count += 1
            except OSError as exc:
                logger.error("Failed to write NFO for %s: %s", video_path, exc)
        return count
