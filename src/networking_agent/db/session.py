from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from networking_agent.config import get_settings
from networking_agent.db.base import Base

_engine = None
_SessionLocal = None


def ensure_sqlite_dir(url: str) -> None:
    """SQLite errors with an opaque 'unable to open database file' if the
    parent directory doesn't exist yet (e.g. a fresh checkout before the
    first `alembic upgrade head`). Anything that opens this URL -- the app
    itself or `network doctor` -- should call this first. Handles relative,
    absolute, and :memory: sqlite URLs via SQLAlchemy's own URL parser
    rather than assuming one specific prefix shape.
    """
    if not url.startswith("sqlite"):
        return
    from sqlalchemy.engine import make_url

    database = make_url(url).database
    if not database or database == ":memory:":
        return
    Path(database).parent.mkdir(parents=True, exist_ok=True)


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        ensure_sqlite_dir(url)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args)
    return _engine


def get_sessionmaker():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def init_db() -> None:
    """Create all tables. Used for local/dev bootstrap; Alembic migrations
    are the source of truth for schema evolution in a shared environment."""
    import networking_agent.db.models  # noqa: F401  (register models on Base)

    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Session:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
