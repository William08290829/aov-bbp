import pytest
from sqlmodel import Session

from admin import db, sync


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Point the database, avatar folder and data.json at a temp dir."""
    avatars = tmp_path / "avatars"
    avatars.mkdir()
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(db, "AVATAR_DIR", avatars)
    monkeypatch.setattr(db, "DATA_JSON", tmp_path / "data.json")
    monkeypatch.setattr(sync, "status", sync.SyncStatus())
    engine = db.make_engine(tmp_path / "app.db")
    db.set_engine(engine)
    db.init_db(engine)
    yield tmp_path
    db.set_engine(None)
    engine.dispose()


@pytest.fixture
def session(paths):
    with db.new_session() as s:
        yield s
