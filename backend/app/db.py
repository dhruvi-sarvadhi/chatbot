"""Database engine and session handling.

One synchronous SQLAlchemy engine for the whole process. Sync on purpose:
every provider call in this app is blocking, FastAPI already runs `def`
endpoints in a threadpool, and the SSE generator that saves a finished turn
is a plain generator — an async session there would need a bridge for no gain.

Connections are pooled, so a request borrows one and gives it straight back.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

log = logging.getLogger("chatbot.db")

settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    # Recycle before Postgres' own idle timeout can hand us a dead socket,
    # and check the connection is alive before handing it to a request.
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def ensure_database() -> None:
    """Create the target database if it does not exist yet.

    Connects to the maintenance database (`postgres`) to do it, because you
    cannot CREATE DATABASE from inside the database you are creating. Silent
    no-op when the database is already there.
    """
    url = make_url(settings.database_url)
    dbname = url.database
    if not dbname:
        raise RuntimeError("DATABASE_URL has no database name")

    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": dbname}
            ).scalar()
            if not exists:
                # Identifiers cannot be bound parameters; dbname comes from our
                # own env file, and quoting keeps any odd characters safe.
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
                log.info("created database %s", dbname)
    finally:
        admin.dispose()


def init_db() -> bool:
    """Create the database and its tables. Returns False if Postgres is down.

    A missing database server must not stop the chatbot from answering — the
    app degrades to not saving anything rather than refusing to start.
    """
    try:
        ensure_database()
        Base.metadata.create_all(engine)
        log.info("database ready: %s", make_url(settings.database_url).render_as_string())
        return True
    except SQLAlchemyError as exc:
        log.error("database unavailable — history will not be saved: %s", exc)
        return False


@contextmanager
def session_scope() -> Iterator[Session]:
    """A transaction that commits on success and rolls back on failure."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency — one session per request."""
    with session_scope() as db:
        yield db
