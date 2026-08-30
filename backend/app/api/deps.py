from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session

from app.core.database import get_engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
        session.commit()
