"""Tests for maestro.db.core."""

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError

from maestro.db.core import create_session, get_engine, init_db
from maestro.db.models import Artist


class TestDbCore:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> Generator[Engine, None, None]:
        db_path = str(tmp_path / "test.db")
        eng = get_engine(db_path, echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_engine_creates_tables(self, engine: Engine) -> None:
        """Verify all tables exist after init_db."""
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        expected = {"artists", "albums", "tracks", "downloads", "filesystem_snapshots", "library_roots"}
        assert expected.issubset(set(tables))

    def test_create_session_and_insert(self, engine: Engine) -> None:
        session = create_session(engine)
        artist = Artist(name="Test", slug="test")
        session.add(artist)
        session.commit()
        assert artist.id is not None
        session.close()

    def test_create_session_rollback_on_error(self, engine: Engine) -> None:
        session = create_session(engine)
        session.add(Artist(name="A", slug="a"))  # valid
        session.add(Artist(name=None, slug=None))  # violates NOT NULL
        with pytest.raises(IntegrityError):
            session.commit()
        session.close()
        # Verify no data was committed
        session2 = create_session(engine)
        assert session2.query(Artist).count() == 0
        session2.close()
