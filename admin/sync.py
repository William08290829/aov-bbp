"""Keep the local SQLite cache and site/data/data.json in sync.

data.json (tracked in git) is the source of truth. Every successful write in
the admin re-exports it; when the file changes on disk (e.g. after git pull)
the database is rebuilt from it.
"""

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlmodel import Session, delete, select

from admin import db, repo
from admin.models import (
    HERO_CLASSES,
    LANES,
    TIERS,
    Counter,
    Hero,
    HeroLane,
    Meta,
    Setting,
    Synergy,
)

TZ = ZoneInfo("Asia/Taipei")
HASH_KEY = "data_json_sha256"

# One request at a time: the admin is single-user and every write re-exports.
# A plain Lock (not RLock): FastAPI may release it from a different thread.
lock = threading.Lock()


class SyncError(RuntimeError):
    """data.json is unreadable; writes are blocked until it is fixed."""


@dataclass
class SyncStatus:
    error: str | None = None          # set while data.json is broken
    imported_notice: bool = False     # one-shot banner after an auto-import
    last_stat: tuple[int, int] | None = None


status = SyncStatus()


# ---------------------------------------------------------------- export


def build_data(session: Session) -> dict:
    heroes = sorted(session.exec(select(Hero)).all(), key=lambda h: h.name)
    names = {h.id: h.name for h in heroes}
    lanes = repo.get_all_lanes(session)

    def pairs(model) -> list[list]:
        rows = []
        for r in session.exec(select(model)).all():
            a, b, v = names[r.a_id], names[r.b_id], r.value
            if a > b:  # order by name; counters flip sign, synergies are symmetric
                a, b = b, a
                v = -v if model is Counter else v
            rows.append([a, b, v])
        return sorted(rows)

    settings = repo.get_settings(session)
    return {
        "exported_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "heroes": [_hero_dict(h, lanes.get(h.id, {})) for h in heroes],
        "counters": pairs(Counter),
        "synergies": pairs(Synergy),
        "settings": {k: _num(settings[k]) for k in sorted(settings)},
    }


def _hero_dict(h: Hero, lanes: dict) -> dict:
    d = {
        "name": h.name,
        "main_class": h.main_class,
        "sub_class": h.sub_class,
        "avatar": h.avatar,
        "form_group": h.form_group,
        "lanes": lanes,
    }
    if h.needs_review:  # admin-only flag; omitted when false to keep lines short
        d["needs_review"] = True
    return d


def _num(v: float) -> float | int:
    return int(v) if float(v).is_integer() and abs(v) < 1e15 else v


def dumps_data(data: dict) -> str:
    """One record per line so git diffs and merges stay readable."""
    d = lambda o: json.dumps(o, ensure_ascii=False)  # noqa: E731

    def block(key: str, items: list) -> str:
        if not items:
            return f'  "{key}": []'
        body = ",\n".join(f"    {d(item)}" for item in items)
        return f'  "{key}": [\n{body}\n  ]'

    parts = [
        f'  "exported_at": {d(data["exported_at"])}',
        block("heroes", data["heroes"]),
        block("counters", data["counters"]),
        block("synergies", data["synergies"]),
        f'  "settings": {d(data["settings"])}',
    ]
    return "{\n" + ",\n".join(parts) + "\n}\n"


@dataclass
class ExportResult:
    data: dict
    changed: bool  # False when data.json already had identical content

    @property
    def summary(self) -> dict:
        return summarize(self.data)


def summarize(data: dict) -> dict:
    return {
        "heroes": len(data["heroes"]),
        "counters": len(data["counters"]),
        "synergies": len(data["synergies"]),
        "exported_at": data.get("exported_at"),
    }


def export_to_disk(session: Session, path: Path | None = None) -> ExportResult:
    path = path or db.DATA_JSON
    data = build_data(session)
    if _same_content(path, data):
        # Nothing changed: keep the file (and its exported_at) to avoid noisy diffs.
        _set_hash(session, _sha256(path.read_bytes()))
        session.commit()
        status.last_stat = _stat(path)
        data["exported_at"] = json.loads(path.read_text(encoding="utf-8")).get("exported_at")
        return ExportResult(data, changed=False)
    raw = dumps_data(data).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)
    _set_hash(session, _sha256(raw))
    session.commit()
    status.last_stat = _stat(path)
    return ExportResult(data, changed=True)


def export_now(session: Session) -> ExportResult:
    """Manual export (CLI / admin button): pick up external changes first, then write.

    Checking first means a stale database can never overwrite a newer data.json
    (e.g. one that just arrived via git pull).
    """
    existed = db.DATA_JSON.exists()
    check(session)  # also creates data.json when it is missing
    result = export_to_disk(session)
    result.changed = result.changed or not existed
    return result


def restore_from(session: Session, source: Path) -> ExportResult:
    """Rebuild the database from `source`, then write it out as data.json.

    Raises SyncError if `source` is not a valid data file; nothing is changed then.
    """
    data = parse_data(source.read_bytes())
    import_data(session, data)
    session.commit()
    return export_to_disk(session)


def _same_content(path: Path, data: dict) -> bool:
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    strip = lambda d: {k: v for k, v in d.items() if k != "exported_at"}  # noqa: E731
    return strip(current) == strip(data)


# ---------------------------------------------------------------- import


def parse_data(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        hint = "（可能是 git 合併衝突標記沒有清乾淨）" if b"<<<<<<<" in raw else ""
        raise SyncError(f"data.json 不是合法的 JSON{hint}：{e}") from e
    _validate(data)
    return data


def _validate(data: dict) -> None:
    def fail(msg: str):
        raise SyncError(f"data.json 內容有誤：{msg}")

    if not isinstance(data, dict):
        fail("最外層必須是物件")
    for key in ("heroes", "counters", "synergies", "settings"):
        if key not in data:
            fail(f"缺少 {key}")
    names: set[str] = set()
    for h in data["heroes"]:
        name = h.get("name")
        if not isinstance(name, str) or not name:
            fail(f"英雄缺少名稱：{h}")
        if name in names:
            fail(f"英雄名稱重複：{name}")
        names.add(name)
        if h.get("main_class") not in HERO_CLASSES + [""]:
            fail(f"{name} 的主職業不合法：{h.get('main_class')}")
        if h.get("sub_class") not in HERO_CLASSES + [None]:
            fail(f"{name} 的副職業不合法：{h.get('sub_class')}")
        for lane, tier in (h.get("lanes") or {}).items():
            if lane not in LANES or tier not in TIERS + [None]:
                fail(f"{name} 的分路或 tier 不合法：{lane}={tier}")
    for key in ("counters", "synergies"):
        seen: set[frozenset] = set()
        for row in data[key]:
            if not (isinstance(row, list) and len(row) == 3 and isinstance(row[2], int)):
                fail(f"{key} 格式錯誤：{row}")
            a, b, _ = row
            if a not in names or b not in names or a == b:
                fail(f"{key} 參照了不存在或相同的英雄：{row}")
            pair = frozenset((a, b))
            if pair in seen:
                fail(f"{key} 同一對英雄出現兩次：{a}、{b}")
            seen.add(pair)


def import_data(session: Session, data: dict) -> None:
    """Replace all hero data with `data`, keeping ids of heroes that still exist."""
    session.exec(delete(HeroLane))
    session.exec(delete(Counter))
    session.exec(delete(Synergy))
    session.exec(delete(Setting))

    existing = {h.name: h for h in session.exec(select(Hero)).all()}
    wanted = {h["name"] for h in data["heroes"]}
    for name, hero in existing.items():
        if name not in wanted:
            session.delete(hero)
    session.flush()

    ids: dict[str, int] = {}
    for h in data["heroes"]:
        hero = existing.get(h["name"]) or Hero(name=h["name"], main_class="")
        hero.main_class = h.get("main_class") or ""
        hero.sub_class = h.get("sub_class")
        hero.avatar = h.get("avatar")
        hero.form_group = repo.derive_form_group(h["name"])
        hero.needs_review = bool(h.get("needs_review")) or hero.main_class == ""
        session.add(hero)
        session.flush()
        ids[h["name"]] = hero.id
        for lane, tier in (h.get("lanes") or {}).items():
            session.add(HeroLane(hero_id=hero.id, lane=lane, tier=tier))

    for a, b, v in data["counters"]:
        repo.set_counter(session, ids[a], ids[b], v)
    for a, b, v in data["synergies"]:
        repo.set_synergy(session, ids[a], ids[b], v)
    for key, value in data["settings"].items():
        session.add(Setting(key=key, value=float(value)))
    session.flush()
    repo.ensure_default_settings(session)


# ---------------------------------------------------------------- auto sync


def check(session: Session) -> bool:
    """Bring the database up to date with data.json.

    Returns True when the database was rebuilt from disk. Raises SyncError when
    data.json is broken (and leaves both the database and the file untouched).
    """
    path = db.DATA_JSON
    st = _stat(path)
    if st is not None and st == status.last_stat and status.error is None:
        return False

    if st is None:
        status.error = None
        if session.exec(select(Hero)).first() is not None:
            export_to_disk(session)
        return False

    raw = path.read_bytes()
    digest = _sha256(raw)
    if digest == _get_hash(session):
        status.error = None
        status.last_stat = st
        return False

    try:
        data = parse_data(raw)
    except SyncError as e:
        status.error = str(e)
        status.last_stat = None
        raise

    import_data(session, data)
    _set_hash(session, digest)
    session.commit()
    status.error = None
    status.last_stat = st
    status.imported_notice = True
    return True


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        s = path.stat()
    except FileNotFoundError:
        return None
    return (s.st_mtime_ns, s.st_size)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _get_hash(session: Session) -> str | None:
    row = session.get(Meta, HASH_KEY)
    return row.value if row else None


def _set_hash(session: Session, digest: str) -> None:
    row = session.get(Meta, HASH_KEY) or Meta(key=HASH_KEY, value=digest)
    row.value = digest
    session.add(row)
