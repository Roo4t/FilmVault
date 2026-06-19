"""Pydantic models for Kodi-compatible NFO data structures."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NFOActor(BaseModel):
    """An actor entry in NFO."""
    name: str
    role: str | None = None
    thumb: str | None = None


class NFOMovie(BaseModel):
    """Kodi-compatible movie NFO schema."""
    title: str
    originaltitle: str | None = None
    sorttitle: str | None = None
    plot: str | None = None
    outline: str | None = None
    thumb: str | None = None          # poster URL or local path
    fanart: list[str] = Field(default_factory=list)
    genre: list[str] = Field(default_factory=list)
    tag: list[str] = Field(default_factory=list)
    year: int | None = None
    premiered: str | None = None      # YYYY-MM-DD
    runtime: int | None = None        # minutes
    rating: float | None = None
    votes: int | None = None
    director: str | None = None
    studio: str | None = None
    actor: list[NFOActor] = Field(default_factory=list)

    # Extended fields
    country: str | None = None
    mpaa: str | None = None
    set_: str | None = Field(default=None, alias="set")
    """Collection / set name (aliased because 'set' is a Python builtin)."""
