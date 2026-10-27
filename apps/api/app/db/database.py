from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.models import Base

engine: Engine
SessionLocal: sessionmaker[Session]


def _prepare_sqlite_directory(database_url: str) -> None:
    database = make_url(database_url).database
    if not database or database == ":memory:":
        return
    path = Path(database).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)


def _build_engine(database_url: str) -> Engine:
    options: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        _prepare_sqlite_directory(database_url)
        options["connect_args"] = {"check_same_thread": False}
        if make_url(database_url).database in (None, "", ":memory:"):
            options["poolclass"] = StaticPool
    db_engine = create_engine(database_url, **options)
    if db_engine.dialect.name == "sqlite":

        @event.listens_for(db_engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return db_engine


def configure_database(database_url: str) -> Engine:
    global engine, SessionLocal
    previous = globals().get("engine")
    new_engine = _build_engine(database_url)
    SessionLocal = sessionmaker(bind=new_engine, autoflush=False, expire_on_commit=False)
    engine = new_engine
    if previous is not None:
        previous.dispose()
    return engine


def create_all(bind: Engine | None = None) -> None:
    Base.metadata.create_all(bind=bind or engine)


def init_db(database_url: str | None = None) -> Engine:
    if database_url is not None and database_url != str(engine.url):
        configure_database(database_url)
    create_all()
    return engine


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


configure_database(get_settings().database_url)
