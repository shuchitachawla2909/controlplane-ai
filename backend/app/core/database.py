"""SQLite persistence via SQLModel. No external database, no migration tool."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings

_settings = get_settings()

_engine = create_engine(
    _settings.db_url,
    echo=False,
    connect_args={"check_same_thread": False} if _settings.db_url.startswith("sqlite") else {},
)


def get_engine():
    return _engine


def init_db() -> None:
    """Create all tables. Import models for side-effect registration first."""
    from app.core import models  # noqa: F401

    SQLModel.metadata.create_all(_engine)


def reset_db() -> None:
    from app.core import models  # noqa: F401

    SQLModel.metadata.drop_all(_engine)
    SQLModel.metadata.create_all(_engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = Session(_engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with Session(_engine) as session:
        yield session
