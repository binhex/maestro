"""SQLAlchemy ORM models for Maestro's music library database."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship  # type: ignore[attr-defined]


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _utcnow() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)


class Artist(Base):
    """A musical artist."""

    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )

    albums: Mapped[list["Album"]] = relationship(
        "Album",
        back_populates="artist",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs: Any) -> None:
        """Initialize an Artist, applying Python-side defaults."""
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class Album(Base):
    """A music album, optionally linked to an artist."""

    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artist_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("artists.id"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genre: Mapped[str | None] = mapped_column(String(128), nullable=True)
    subgenre: Mapped[str | None] = mapped_column(String(128), nullable=True)
    artwork_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    fanart_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )

    artist: Mapped[Artist | None] = relationship("Artist", back_populates="albums")
    tracks: Mapped[list["Track"]] = relationship(
        "Track",
        back_populates="album",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs: Any) -> None:
        """Initialize an Album, applying Python-side defaults."""
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class Track(Base):
    """An individual track file in a music library."""

    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    album_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("albums.id"),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    track_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )

    album: Mapped[Album | None] = relationship("Album", back_populates="tracks")

    def __init__(self, **kwargs: Any) -> None:
        """Initialize a Track, applying Python-side defaults."""
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class Download(Base):
    """A download record tracking the lifecycle of an incoming release."""

    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="new",
        index=True,
    )
    match_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    identified_artist: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identified_album: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identified_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    identified_genre: Mapped[str | None] = mapped_column(String(128), nullable=True)
    identified_album_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("albums.id"),
        nullable=True,
    )
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __init__(self, **kwargs: Any) -> None:
        """Initialize a Download, applying Python-side defaults."""
        kwargs.setdefault("status", "new")
        kwargs.setdefault("retry_count", 0)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class FileSystemSnapshot(Base):
    """A point-in-time snapshot of a file on the filesystem."""

    __tablename__ = "filesystem_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )

    def __init__(self, **kwargs: Any) -> None:
        """Initialize a FileSystemSnapshot, applying Python-side defaults."""
        kwargs.setdefault("first_seen_at", _utcnow())
        super().__init__(**kwargs)


class LibraryRoot(Base):
    """A configured root directory in the music library."""

    __tablename__ = "library_roots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="library",
    )
    enabled: Mapped[bool] = mapped_column(default=True)
    source_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    destination_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )

    def __init__(self, **kwargs: Any) -> None:
        """Initialize a LibraryRoot, applying Python-side defaults."""
        kwargs.setdefault("enabled", True)
        kwargs.setdefault("type", "library")
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)
