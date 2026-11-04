import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

ROOT = Path(__file__).resolve().parent.parent

# Module-level paths; tests override them with monkeypatch.
DB_PATH = Path(os.environ.get("BBP_DB", ROOT / "data" / "app.db"))
AVATAR_DIR = ROOT / "site" / "avatars"
DATA_JSON = ROOT / "site" / "data" / "data.json"

_engine: Engine | None = None


def make_engine(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = make_engine(DB_PATH)
    return _engine


def set_engine(engine: Engine | None) -> None:
    global _engine
    _engine = engine


def init_db(engine: Engine | None = None) -> None:
    from admin import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine or get_engine())


def new_session() -> Session:
    return Session(get_engine())
