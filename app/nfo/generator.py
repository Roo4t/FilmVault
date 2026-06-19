"""NFO XML generator using Jinja2 templates."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.database.models import Metadata
from app.genre_mapper import map_genres
from app.nfo.schema import NFOActor, NFOMovie

# Jinja2 environment — loads templates from the templates/ directory
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


class NFOGenerator:
    """
    Generates Kodi-compatible NFO XML from metadata records.

    Usage:
        gen = NFOGenerator()
        xml = gen.generate(metadata_record)
        print(xml)
    """

    # Maximum plot length to avoid bloated NFO files
    MAX_PLOT_LENGTH = 5000

    # Maximum fanart images
    MAX_FANART = 10

    def generate(self, metadata: Metadata) -> str:
        """
        Generate NFO XML string from a database Metadata record.

        Args:
            metadata: SQLAlchemy Metadata model instance.

        Returns:
            Kodi-compatible XML string.
        """
        movie = self._to_schema(metadata)
        return self.generate_from_schema(movie)

    def generate_from_schema(self, movie: NFOMovie) -> str:
        """
        Generate NFO XML from a Pydantic NFOMovie schema.

        Args:
            movie: NFOMovie model instance.

        Returns:
            Kodi-compatible XML string.
        """
        template = _jinja_env.get_template("movie.nfo.j2")
        xml = template.render(**movie.model_dump(by_alias=True))

        # Collapse blank lines
        lines = [line for line in xml.splitlines() if line.strip()]
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _to_schema(self, meta: Metadata) -> NFOMovie:
        """Convert a SQLAlchemy Metadata record to an NFOMovie schema."""
        actors = [
            NFOActor(
                name=a.get("name", ""),
                role=a.get("role"),
                thumb=a.get("thumb"),
            )
            for a in (meta.actors or [])
        ]

        plot = (meta.plot or "")[:self.MAX_PLOT_LENGTH]
        fanart = (meta.fanart_urls or [])[:self.MAX_FANART]

        return NFOMovie(
            title=meta.title,
            originaltitle=meta.original_title,
            plot=plot,
            thumb=meta.poster_url,
            fanart=fanart,
            genre=map_genres(meta.genres or []),  # 应用 Genre 映射
            tag=meta.tags or [],
            year=meta.year,
            premiered=meta.premiered,
            runtime=meta.runtime,
            rating=meta.rating,
            director=meta.director,
            studio=meta.studio,
            actor=actors,
        )
