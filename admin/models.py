from enum import Enum

from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel


class Lane(str, Enum):
    SLAYER = "凱撒"
    JUNGLE = "打野"
    MID = "中路"
    DRAGON = "魔龍"
    SUPPORT = "輔助"


class HeroClass(str, Enum):
    TANK = "坦克"
    WARRIOR = "戰士"
    ASSASSIN = "刺客"
    MAGE = "法師"
    MARKSMAN = "射手"
    SUPPORT = "輔助"


LANES: list[str] = [lane.value for lane in Lane]
HERO_CLASSES: list[str] = [c.value for c in HeroClass]
TIERS: list[str] = ["T0", "T1", "T2"]

DEFAULT_SETTINGS: dict[str, float] = {
    "w_tier": 1.0,
    "w_counter": 1.0,
    "w_synergy": 0.7,
    "w_risk": 0.5,
    "w_deny": 0.5,
    "w_ban_threat": 1.0,
    "tier_T0": 3,
    "tier_T1": 2,
    "tier_T2": 1,
    "tier_none": 0,
}


def _in(column: str, values: list[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Hero(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    main_class: str
    sub_class: str | None = None
    avatar: str | None = None        # file name under site/avatars/
    form_group: str | None = None    # derived from name, e.g. "元流之子"
    needs_review: bool = False


class HeroLane(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(_in("lane", LANES), name="ck_herolane_lane"),
        CheckConstraint(f"tier IS NULL OR {_in('tier', TIERS)}", name="ck_herolane_tier"),
    )

    hero_id: int = Field(foreign_key="hero.id", primary_key=True)
    lane: str = Field(primary_key=True)
    tier: str | None = None


class Counter(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint("a_id < b_id", name="ck_counter_order"),
        CheckConstraint("value != 0", name="ck_counter_nonzero"),
    )

    a_id: int = Field(foreign_key="hero.id", primary_key=True)
    b_id: int = Field(foreign_key="hero.id", primary_key=True)
    value: int        # >0: a counters b; <0: b counters a


class Synergy(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint("a_id < b_id", name="ck_synergy_order"),
        CheckConstraint("value != 0", name="ck_synergy_nonzero"),
    )

    a_id: int = Field(foreign_key="hero.id", primary_key=True)
    b_id: int = Field(foreign_key="hero.id", primary_key=True)
    value: int        # >0: good together; <0: bad together


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: float


class Meta(SQLModel, table=True):
    """Internal bookkeeping (e.g. hash of the last synced data.json)."""

    key: str = Field(primary_key=True)
    value: str
