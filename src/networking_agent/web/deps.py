"""Per-request DB session + AgentContext dependency. Mirrors
db.session.session_scope but as a FastAPI generator dependency: one
session per request, committed on success, rolled back on exception."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from networking_agent.agents.context import AgentContext
from networking_agent.db.session import get_sessionmaker


def get_db() -> Generator[Session, None, None]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_ctx(session: Session) -> AgentContext:
    return AgentContext.build(session)
