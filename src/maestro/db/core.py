"""Database engine and session management."""

from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from maestro.db.models import Base


def get_engine(db_path: str, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for the given SQLite database path.

    Args:
        db_path: Path to the SQLite database file.
        echo: If True, log all SQL statements.

    Returns:
        A configured SQLAlchemy Engine instance.
    """
    # Ensure parent directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=echo)


def init_db(engine: Engine) -> None:
    """Create all tables defined in the ORM models.

    Safe to call multiple times; uses IF NOT EXISTS internally.
    """
    Base.metadata.create_all(engine)


@lru_cache(maxsize=16)
def _make_session_factory(dsn: str) -> sessionmaker:
    """Create and cache a sessionmaker for the given DSN.

    Cached to avoid recreating sessionmaker on every call.
    The DSN acts as cache key since engines with the same DSN
    share the same factory.
    """
    engine = create_engine(dsn)
    return sessionmaker(bind=engine)


def create_session(engine: Engine) -> Session:
    """Create a new session bound to the given engine.

    Returns:
        A SQLAlchemy Session instance.
    """
    dsn = str(engine.url.render_as_string(hide_password=False))
    factory = _make_session_factory(dsn)
    session: Session = factory()
    return session


@contextmanager
def get_session(engine: Engine) -> Generator[Session, None, None]:
    """Yield a session as a context manager, closing it on exit.

    Usage:
        with get_session(engine) as session:
            session.query(...)
    """
    session = create_session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
