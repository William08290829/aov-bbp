"""All reads and writes of hero data go through this module.

Functions here flush but never commit; callers own the transaction.
Counter / synergy sign and ordering rules live only here.
"""

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session, delete, or_, select

from admin import db
from admin.models import (
    DEFAULT_SETTINGS,
    HERO_CLASSES,
    LANES,
    TIERS,
    Counter,
    Hero,
    HeroLane,
    Setting,
    Synergy,
)


class RepoError(ValueError):
    """Validation error; the message is user-facing (Traditional Chinese)."""


# ---------------------------------------------------------------- names

FORBIDDEN_NAME_CHARS = set('/\\:*?"<>|')
_FORM_RE = re.compile(r"^(.+?)\((.+)\)$")


def normalize_name(raw: str) -> str:
    name = (raw or "").strip().replace("（", "(").replace("）", ")")
    if not name:
        raise RepoError("英雄名稱不可為空")
    bad = sorted({c for c in name if c in FORBIDDEN_NAME_CHARS})
    if bad:
        raise RepoError(f"英雄名稱不可包含這些字元：{' '.join(bad)}")
    if any(ord(c) < 32 for c in name):
        raise RepoError("英雄名稱不可包含控制字元")
    return name


def derive_form_group(name: str) -> str | None:
    m = _FORM_RE.match(name)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------- classes


def validate_classes(main_class: str, sub_class: str | None) -> tuple[str, str | None]:
    main_class = (main_class or "").strip()
    sub_class = (sub_class or "").strip() or None
    if main_class not in HERO_CLASSES:
        raise RepoError("請選擇主職業")
    if sub_class is not None:
        if sub_class not in HERO_CLASSES:
            raise RepoError(f"副職業不合法：{sub_class}")
        if sub_class == main_class:
            raise RepoError("副職業不可與主職業相同")
    return main_class, sub_class


# ---------------------------------------------------------------- heroes


def get_hero(session: Session, hero_id: int) -> Hero:
    hero = session.get(Hero, hero_id)
    if hero is None:
        raise RepoError("找不到這隻英雄（可能已被刪除）")
    return hero


def get_hero_by_name(session: Session, name: str) -> Hero | None:
    return session.exec(select(Hero).where(Hero.name == name)).first()


def _ensure_name_free(session: Session, name: str, exclude_id: int | None = None) -> None:
    other = get_hero_by_name(session, name)
    if other is not None and other.id != exclude_id:
        raise RepoError(f"已經有名為「{name}」的英雄")


def create_hero(
    session: Session,
    name: str,
    main_class: str,
    sub_class: str | None = None,
) -> Hero:
    name = normalize_name(name)
    main_class, sub_class = validate_classes(main_class, sub_class)
    _ensure_name_free(session, name)
    hero = Hero(
        name=name,
        main_class=main_class,
        sub_class=sub_class,
        form_group=derive_form_group(name),
    )
    session.add(hero)
    session.flush()
    return hero


def update_hero(
    session: Session,
    hero_id: int,
    name: str,
    main_class: str,
    sub_class: str | None,
) -> Hero:
    hero = get_hero(session, hero_id)
    name = normalize_name(name)
    main_class, sub_class = validate_classes(main_class, sub_class)
    _ensure_name_free(session, name, exclude_id=hero.id)

    old_name = hero.name
    hero.main_class = main_class
    hero.sub_class = sub_class
    if name != old_name:
        hero.name = name
        hero.form_group = derive_form_group(name)
        if hero.avatar:
            hero.avatar = _rename_avatar_file(hero.avatar, name)
    session.add(hero)
    session.flush()
    return hero


def mark_reviewed(session: Session, hero_id: int) -> Hero:
    hero = get_hero(session, hero_id)
    if hero.main_class not in HERO_CLASSES:
        raise RepoError("請先補上主職業，才能標記為已確認")
    hero.needs_review = False
    session.add(hero)
    session.flush()
    return hero


def delete_hero(session: Session, hero_id: int) -> None:
    hero = get_hero(session, hero_id)
    session.exec(delete(HeroLane).where(HeroLane.hero_id == hero_id))
    for model in (Counter, Synergy):
        session.exec(delete(model).where(or_(model.a_id == hero_id, model.b_id == hero_id)))
    avatar = hero.avatar
    session.delete(hero)
    session.flush()
    if avatar:
        (db.AVATAR_DIR / avatar).unlink(missing_ok=True)


def list_heroes(session: Session) -> list[Hero]:
    order = {c: i for i, c in enumerate(HERO_CLASSES)}
    heroes = session.exec(select(Hero)).all()
    return sorted(heroes, key=lambda h: (order.get(h.main_class, len(order)), h.name))


# ---------------------------------------------------------------- avatars

AVATAR_EXTS = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png", ".webp": ".webp"}
MAX_AVATAR_BYTES = 5 * 1024 * 1024


def _sniff_image_ext(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _remove_avatar_files(name: str, keep: str | None = None) -> None:
    for ext in set(AVATAR_EXTS.values()):
        fname = f"{name}{ext}"
        if fname != keep:
            (db.AVATAR_DIR / fname).unlink(missing_ok=True)


def _rename_avatar_file(old_fname: str, new_name: str) -> str | None:
    old_path = db.AVATAR_DIR / old_fname
    if not old_path.exists():
        return None
    new_fname = f"{new_name}{old_path.suffix.lower()}"
    _remove_avatar_files(new_name)  # drop stale files that would collide
    old_path.rename(db.AVATAR_DIR / new_fname)
    return new_fname


def save_avatar(session: Session, hero_id: int, filename: str, data: bytes) -> Hero:
    hero = get_hero(session, hero_id)
    ext = AVATAR_EXTS.get(Path(filename or "").suffix.lower())
    if ext is None:
        raise RepoError("頭像只接受 jpg、png、webp")
    if not data:
        raise RepoError("上傳的檔案是空的")
    if len(data) > MAX_AVATAR_BYTES:
        raise RepoError("頭像檔案不可超過 5 MB")
    if _sniff_image_ext(data) != ext:
        raise RepoError("檔案內容與副檔名不符，請確認是 jpg、png 或 webp 圖片")

    fname = f"{hero.name}{ext}"
    db.AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    (db.AVATAR_DIR / fname).write_bytes(data)
    _remove_avatar_files(hero.name, keep=fname)
    hero.avatar = fname
    session.add(hero)
    session.flush()
    return hero


def avatar_mtime(hero: Hero) -> int | None:
    if not hero.avatar:
        return None
    try:
        return int((db.AVATAR_DIR / hero.avatar).stat().st_mtime)
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------- lanes


def get_lanes(session: Session, hero_id: int) -> dict[str, str | None]:
    rows = session.exec(select(HeroLane).where(HeroLane.hero_id == hero_id)).all()
    by_lane = {r.lane: r.tier for r in rows}
    return {lane: by_lane[lane] for lane in LANES if lane in by_lane}


def get_all_lanes(session: Session) -> dict[int, dict[str, str | None]]:
    result: dict[int, dict[str, str | None]] = {}
    for r in session.exec(select(HeroLane)).all():
        result.setdefault(r.hero_id, {})[r.lane] = r.tier
    return {
        hid: {lane: lanes[lane] for lane in LANES if lane in lanes}
        for hid, lanes in result.items()
    }


def set_lane(session: Session, hero_id: int, lane: str, enabled: bool, tier: str | None = None) -> None:
    """Enable/disable a lane; a newly enabled lane starts unrated unless tier is given."""
    get_hero(session, hero_id)
    if lane not in LANES:
        raise RepoError(f"分路不合法：{lane}")
    tier = tier or None
    if tier is not None and tier not in TIERS:
        raise RepoError(f"tier 不合法：{tier}")

    row = session.get(HeroLane, (hero_id, lane))
    if not enabled:
        if row is not None:
            session.delete(row)
    elif row is None:
        session.add(HeroLane(hero_id=hero_id, lane=lane, tier=tier))
    else:
        row.tier = tier
        session.add(row)
    session.flush()


# ---------------------------------------------------------------- counters / synergies


def _pair(x: int, y: int) -> tuple[int, int, int]:
    """Return (a, b, sign) with a < b; sign is -1 when the pair was swapped."""
    if x == y:
        raise RepoError("英雄不能和自己建立剋制或搭配關係")
    return (x, y, 1) if x < y else (y, x, -1)


def get_counter(session: Session, x: int, y: int) -> int:
    """>0: x counters y; <0: y counters x."""
    a, b, sign = _pair(x, y)
    row = session.get(Counter, (a, b))
    return sign * row.value if row else 0


def set_counter(session: Session, x: int, y: int, value: int) -> None:
    a, b, sign = _pair(x, y)
    _store(session, Counter, a, b, sign * int(value))


def get_synergy(session: Session, x: int, y: int) -> int:
    a, b, _ = _pair(x, y)
    row = session.get(Synergy, (a, b))
    return row.value if row else 0


def set_synergy(session: Session, x: int, y: int, value: int) -> None:
    a, b, _ = _pair(x, y)
    _store(session, Synergy, a, b, int(value))


def _store(session: Session, model, a: int, b: int, value: int) -> None:
    get_hero(session, a)
    get_hero(session, b)
    row = session.get(model, (a, b))
    if value == 0:
        if row is not None:
            session.delete(row)
    elif row is None:
        session.add(model(a_id=a, b_id=b, value=value))
    else:
        row.value = value
        session.add(row)
    session.flush()


def counters_of(session: Session, hero_id: int) -> dict[int, int]:
    """counter(hero, other) for every other hero with a non-zero relation."""
    rows = session.exec(
        select(Counter).where(or_(Counter.a_id == hero_id, Counter.b_id == hero_id))
    ).all()
    return {
        (r.b_id if r.a_id == hero_id else r.a_id): (r.value if r.a_id == hero_id else -r.value)
        for r in rows
    }


def synergies_of(session: Session, hero_id: int) -> dict[int, int]:
    rows = session.exec(
        select(Synergy).where(or_(Synergy.a_id == hero_id, Synergy.b_id == hero_id))
    ).all()
    return {(r.b_id if r.a_id == hero_id else r.a_id): r.value for r in rows}


COUNTER_CYCLE = [0, 1, 2, -1, -2]
SYNERGY_CYCLE = [0, 1, 2]


def next_counter_value(current: int) -> int:
    """UI toggle order: 0 -> +1 -> +2 -> -1 -> -2 -> 0 (out-of-range values are clamped)."""
    return _next_in_cycle(COUNTER_CYCLE, max(-2, min(2, current)))


def next_synergy_value(current: int) -> int:
    """UI toggle order: 0 -> +1 -> +2 -> 0. A legacy negative value is cleared."""
    return _next_in_cycle(SYNERGY_CYCLE, min(2, current)) if current >= 0 else 0


def _next_in_cycle(cycle: list[int], current: int) -> int:
    return cycle[(cycle.index(current) + 1) % len(cycle)]


# ---------------------------------------------------------------- settings


def ensure_default_settings(session: Session) -> None:
    existing = set(session.exec(select(Setting.key)).all())
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            session.add(Setting(key=key, value=float(value)))
    session.flush()


def get_settings(session: Session) -> dict[str, float]:
    return {s.key: s.value for s in session.exec(select(Setting)).all()}


SETTING_LIMIT = 100.0


def set_setting(session: Session, key: str, raw: str | float) -> float:
    if key not in DEFAULT_SETTINGS:
        raise RepoError(f"未知的設定：{key}")
    try:
        value = float(str(raw).strip())
    except ValueError:
        raise RepoError("請輸入數字") from None
    if not math.isfinite(value) or abs(value) > SETTING_LIMIT:
        raise RepoError(f"數值必須介於 -{SETTING_LIMIT:g} 到 {SETTING_LIMIT:g} 之間")
    row = session.get(Setting, key) or Setting(key=key, value=value)
    row.value = value
    session.add(row)
    session.flush()
    return value


def reset_settings(session: Session) -> None:
    for key, value in DEFAULT_SETTINGS.items():
        row = session.get(Setting, key) or Setting(key=key, value=float(value))
        row.value = float(value)
        session.add(row)
    session.flush()


# ---------------------------------------------------------------- stats


@dataclass
class Stats:
    total: int = 0
    with_lanes: int = 0
    with_counters: int = 0
    needs_review: int = 0
    form_groups: dict[str, list[str]] = field(default_factory=dict)


def get_stats(session: Session) -> Stats:
    heroes = session.exec(select(Hero)).all()
    lane_ids = set(session.exec(select(HeroLane.hero_id)).all())
    counter_ids = hero_ids_with_counters(session)
    groups: dict[str, list[str]] = {}
    for h in heroes:
        if h.form_group:
            groups.setdefault(h.form_group, []).append(h.name)
    return Stats(
        total=len(heroes),
        with_lanes=sum(1 for h in heroes if h.id in lane_ids),
        with_counters=sum(1 for h in heroes if h.id in counter_ids),
        needs_review=sum(1 for h in heroes if h.needs_review),
        form_groups={k: sorted(v) for k, v in sorted(groups.items())},
    )


def hero_ids_with_counters(session: Session) -> set[int]:
    ids: set[int] = set()
    for a, b in session.exec(select(Counter.a_id, Counter.b_id)).all():
        ids.update((a, b))
    return ids

