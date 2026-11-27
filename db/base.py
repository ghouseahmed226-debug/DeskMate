"""SQLAlchemy engine and session management supporting SQLite (dev/test) and PostgreSQL."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import get_settings


class Base(DeclarativeBase):
    """Base class for all DeskMate ORM models."""


_ENGINE_CACHE: dict[str, Engine] = {}
_SESSION_FACTORY_CACHE: dict[str, sessionmaker[Session]] = {}


def get_engine(database_url: Optional[str] = None) -> Engine:
    url = database_url or get_settings().database_url
    if url in _ENGINE_CACHE:
        return _ENGINE_CACHE[url]

    connect_args = {}
    engine_kwargs = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    else:
        engine_kwargs["pool_size"] = 10
        engine_kwargs["max_overflow"] = 20

    engine = create_engine(url, connect_args=connect_args, **engine_kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _conn_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    _ENGINE_CACHE[url] = engine
    return engine


def get_session_factory(database_url: Optional[str] = None) -> sessionmaker[Session]:
    url = database_url or get_settings().database_url
    if url not in _SESSION_FACTORY_CACHE:
        engine = get_engine(url)
        _SESSION_FACTORY_CACHE[url] = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _SESSION_FACTORY_CACHE[url]


def init_db(database_url: Optional[str] = None) -> Engine:
    """Creates all tables if not already migrated (dev/test convenience)."""
    import db.models  # noqa: F401

    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)
    return engine


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped SQLAlchemy session."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope(database_url: Optional[str] = None) -> Generator[Session, None, None]:
    """Context manager with automatic commit/rollback for non-HTTP callers."""
    factory = get_session_factory(database_url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
