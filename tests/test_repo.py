import json

import pytest
from sqlmodel import select

from admin import db, repo, sync
from admin.models import DEFAULT_SETTINGS, Counter, Hero, HeroLane, Synergy
from scripts.import_heroes import import_csv

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 16
JPG = b"\xff\xd8\xff\xe0" + b"\0" * 16


def make(session, name, main="法師", sub=None):
    return repo.create_hero(session, name, main, sub)


@pytest.fixture
def abc(session):
    a, b, c = make(session, "甲"), make(session, "乙"), make(session, "丙")
    session.commit()
    return a.id, b.id, c.id


# ---------------------------------------------------------------- counters / synergies


def test_counter_is_antisymmetric_and_stored_once(session, abc):
    a, b, _ = abc
    repo.set_counter(session, b, a, 1)  # b counters a, written in reverse order
    assert repo.get_counter(session, b, a) == 1
    assert repo.get_counter(session, a, b) == -1
    rows = session.exec(select(Counter)).all()
    assert len(rows) == 1
    assert (rows[0].a_id, rows[0].b_id, rows[0].value) == (min(a, b), max(a, b), -1 if a < b else 1)


def test_counter_overwrite_from_either_side(session, abc):
    a, b, _ = abc
    repo.set_counter(session, a, b, 1)
    repo.set_counter(session, b, a, 2)
    assert repo.get_counter(session, a, b) == -2
    assert len(session.exec(select(Counter)).all()) == 1


def test_synergy_is_symmetric(session, abc):
    a, b, _ = abc
    repo.set_synergy(session, b, a, -1)
    assert repo.get_synergy(session, a, b) == -1
    assert repo.get_synergy(session, b, a) == -1
    assert len(session.exec(select(Synergy)).all()) == 1


def test_zero_deletes_row(session, abc):
    a, b, _ = abc
    repo.set_counter(session, a, b, 1)
    repo.set_synergy(session, a, b, 1)
    repo.set_counter(session, b, a, 0)
    repo.set_synergy(session, b, a, 0)
    assert session.exec(select(Counter)).all() == []
    assert session.exec(select(Synergy)).all() == []
    assert repo.get_counter(session, a, b) == 0


def test_counter_and_synergy_are_independent(session, abc):
    a, b, _ = abc
    repo.set_counter(session, a, b, 1)
    repo.set_synergy(session, a, b, 1)
    repo.set_counter(session, a, b, 0)
    assert repo.get_synergy(session, a, b) == 1


def test_self_relation_rejected(session, abc):
    a, _, _ = abc
    with pytest.raises(repo.RepoError):
        repo.set_counter(session, a, a, 1)
    with pytest.raises(repo.RepoError):
        repo.get_synergy(session, a, a)


def test_relations_of_hero_from_its_perspective(session, abc):
    a, b, c = abc
    repo.set_counter(session, a, b, 1)
    repo.set_counter(session, c, a, 1)
    repo.set_synergy(session, c, a, -1)
    assert repo.counters_of(session, a) == {b: 1, c: -1}
    assert repo.counters_of(session, c) == {a: 1}
    assert repo.synergies_of(session, a) == {c: -1}


def test_cycle_order():
    assert [repo.next_counter_value(v) for v in (0, 1, 2, -1, -2)] == [1, 2, -1, -2, 0]
    assert repo.next_counter_value(3) == -1 and repo.next_counter_value(-5) == 0
    assert [repo.next_synergy_value(v) for v in (0, 1, 2, 3, -1)] == [1, 2, 0, 0, 0]


# ---------------------------------------------------------------- heroes


def test_delete_hero_cascades(session, abc, paths):
    a, b, c = abc
    repo.set_lane(session, a, "中路", True, "T0")
    repo.set_counter(session, a, b, 1)
    repo.set_counter(session, c, a, 1)
    repo.set_synergy(session, a, c, 1)
    repo.set_counter(session, b, c, 1)  # unrelated, must survive
    repo.save_avatar(session, a, "x.png", PNG)
    session.commit()

    repo.delete_hero(session, a)
    session.commit()
    assert session.get(Hero, a) is None
    assert session.exec(select(HeroLane)).all() == []
    assert [(r.a_id, r.b_id) for r in session.exec(select(Counter)).all()] == [(min(b, c), max(b, c))]
    assert session.exec(select(Synergy)).all() == []
    assert not (paths / "avatars" / "甲.png").exists()


def test_name_normalization_and_validation(session):
    h = make(session, "  元流之子（法師）  ")
    assert h.name == "元流之子(法師)"
    assert h.form_group == "元流之子"
    assert make(session, "莉莉安").form_group is None
    for bad in ("", "   ", "a/b", "x:y", 'q"'):
        with pytest.raises(repo.RepoError):
            make(session, bad)
    with pytest.raises(repo.RepoError):
        make(session, "元流之子(法師)")  # duplicate


def test_class_validation(session):
    with pytest.raises(repo.RepoError):
        make(session, "甲", main="中路")
    with pytest.raises(repo.RepoError):
        make(session, "甲", main="法師", sub="法師")
    assert make(session, "甲", main="法師", sub="").sub_class is None


def test_rename_updates_form_group_and_avatar(session, paths):
    h = make(session, "甲")
    repo.save_avatar(session, h.id, "a.JPEG", JPG)
    assert h.avatar == "甲.jpg"
    repo.update_hero(session, h.id, "乙(射手)", "射手", None)
    assert h.name == "乙(射手)"
    assert h.form_group == "乙"
    assert h.avatar == "乙(射手).jpg"
    assert (paths / "avatars" / "乙(射手).jpg").read_bytes() == JPG
    assert not (paths / "avatars" / "甲.jpg").exists()


def test_avatar_replaces_other_extension(session, paths):
    h = make(session, "甲")
    repo.save_avatar(session, h.id, "a.jpg", JPG)
    repo.save_avatar(session, h.id, "b.png", PNG)
    assert h.avatar == "甲.png"
    assert sorted(p.name for p in (paths / "avatars").iterdir()) == ["甲.png"]


def test_avatar_rejects_bad_files(session):
    h = make(session, "甲")
    for fname, data in (("a.gif", PNG), ("a.png", JPG), ("a.png", b""), ("a.svg", b"<svg/>")):
        with pytest.raises(repo.RepoError):
            repo.save_avatar(session, h.id, fname, data)


def test_mark_reviewed_requires_main_class(session):
    h = Hero(name="甲", main_class="", needs_review=True)
    session.add(h)
    session.flush()
    with pytest.raises(repo.RepoError):
        repo.mark_reviewed(session, h.id)
    repo.update_hero(session, h.id, "甲", "坦克", None)
    assert repo.mark_reviewed(session, h.id).needs_review is False


def test_lanes(session):
    h = make(session, "甲")
    repo.set_lane(session, h.id, "打野", True)
    assert repo.get_lanes(session, h.id) == {"打野": None}
    repo.set_lane(session, h.id, "打野", True, "T1")
    repo.set_lane(session, h.id, "凱撒", True, "T2")
    assert repo.get_lanes(session, h.id) == {"凱撒": "T2", "打野": "T1"}
    repo.set_lane(session, h.id, "打野", False, "T1")
    assert repo.get_lanes(session, h.id) == {"凱撒": "T2"}
    with pytest.raises(repo.RepoError):
        repo.set_lane(session, h.id, "射手", True)
    with pytest.raises(repo.RepoError):
        repo.set_lane(session, h.id, "中路", True, "T9")


def test_stats(session, abc):
    a, b, c = abc
    repo.set_lane(session, a, "中路", True)
    repo.set_counter(session, b, c, -1)
    session.get(Hero, a).needs_review = True
    st = repo.get_stats(session)
    assert (st.total, st.with_lanes, st.with_counters, st.needs_review) == (3, 1, 2, 1)


def test_default_settings_fill_missing_only(session):
    repo.ensure_default_settings(session)
    from admin.models import Setting
    session.get(Setting, "w_tier").value = 9
    session.delete(session.get(Setting, "w_risk"))
    session.flush()
    repo.ensure_default_settings(session)
    s = repo.get_settings(session)
    assert s["w_tier"] == 9
    assert s["w_risk"] == DEFAULT_SETTINGS["w_risk"]


# ---------------------------------------------------------------- import_heroes


def test_import_csv(session, paths):
    csv_path = paths / "heroes.csv"
    csv_path.write_text(
        "﻿name,classes\r\n"
        "薩尼,坦克\r\n"
        "贊尼爾,輔助|坦克\r\n"
        "壞主,中路|法師\r\n"
        "全壞,中路|打野\r\n"
        "壞副,射手|魔龍\r\n"
        "重複,法師|法師\r\n"
        "元流之子（法師）,法師\r\n"
        "a/b,法師\r\n",
        encoding="utf-8",
    )
    report = import_csv(session, csv_path)
    session.commit()
    heroes = {h.name: h for h in session.exec(select(Hero)).all()}
    assert (heroes["贊尼爾"].main_class, heroes["贊尼爾"].sub_class) == ("輔助", "坦克")
    assert (heroes["壞主"].main_class, heroes["壞主"].sub_class, heroes["壞主"].needs_review) == ("法師", None, True)
    assert (heroes["全壞"].main_class, heroes["全壞"].needs_review) == ("", True)
    assert (heroes["壞副"].sub_class, heroes["壞副"].needs_review) == (None, True)
    assert (heroes["重複"].sub_class, heroes["重複"].needs_review) == (None, True)
    assert heroes["元流之子(法師)"].form_group == "元流之子"
    assert heroes["薩尼"].needs_review is False
    assert "a/b" not in heroes
    assert len(report.added) == 7
    assert set(repo.get_settings(session)) == set(DEFAULT_SETTINGS)

    again = import_csv(session, csv_path)
    assert again.added == [] and len(again.skipped) == 7


def test_real_heroes_csv_imports_cleanly(session):
    report = import_csv(session, db.ROOT / "data" / "heroes.csv")
    assert len(report.added) == 130
    assert report.review == []
    groups = repo.get_stats(session).form_groups
    assert groups == {"元流之子": ["元流之子(射手)", "元流之子(法師)"]}


# ---------------------------------------------------------------- data.json sync


def populate(session):
    a, b, c = make(session, "甲", "坦克", "輔助"), make(session, "乙(射手)", "射手"), make(session, "丙")
    repo.set_lane(session, a.id, "輔助", True, "T1")
    repo.set_lane(session, a.id, "凱撒", True)
    repo.set_counter(session, a.id, b.id, 1)
    repo.set_counter(session, c.id, a.id, 2)
    repo.set_synergy(session, b.id, c.id, -1)
    c.needs_review = True
    repo.ensure_default_settings(session)
    session.commit()


def test_export_format_one_record_per_line(session, paths):
    populate(session)
    sync.export_to_disk(session)
    text = (paths / "data.json").read_text(encoding="utf-8")
    data = json.loads(text)
    assert [h["name"] for h in data["heroes"]] == sorted(["甲", "乙(射手)", "丙"])
    assert ["甲", "乙(射手)", 1] in data["counters"] or ["乙(射手)", "甲", -1] in data["counters"]
    assert all(row[0] < row[1] for row in data["counters"] + data["synergies"])
    lines = text.splitlines()
    for row in data["counters"] + data["synergies"]:
        assert any(json.dumps(row, ensure_ascii=False) in line for line in lines)
    assert sum('"name":' in line for line in lines) == 3  # one hero per line
    hero = next(h for h in data["heroes"] if h["name"] == "丙")
    assert hero["needs_review"] is True
    assert "needs_review" not in next(h for h in data["heroes"] if h["name"] == "甲")


def snapshot(session) -> dict:
    data = sync.build_data(session)
    data.pop("exported_at")
    return data


def test_export_import_roundtrip(session, paths):
    populate(session)
    before = snapshot(session)
    sync.export_to_disk(session)

    # Fresh database (as on the other machine), then auto-import.
    engine = db.make_engine(paths / "other.db")
    db.init_db(engine)
    db.set_engine(engine)
    sync.status.last_stat = None
    with db.new_session() as other:
        assert sync.check(other) is True
        assert snapshot(other) == before


def test_check_detects_external_change(session, paths):
    populate(session)
    sync.export_to_disk(session)
    assert sync.check(session) is False

    data = json.loads((paths / "data.json").read_text(encoding="utf-8"))
    data["heroes"].append({"name": "新英雄", "main_class": "法師", "sub_class": None,
                           "avatar": None, "form_group": None, "lanes": {"中路": "T0"}})
    (paths / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    old_ids = {h.name: h.id for h in session.exec(select(Hero)).all()}
    assert sync.check(session) is True
    hero = repo.get_hero_by_name(session, "新英雄")
    assert repo.get_lanes(session, hero.id) == {"中路": "T0"}
    # Ids of heroes that still exist are preserved across re-imports.
    assert {n: i for n, i in ((h.name, h.id) for h in session.exec(select(Hero)).all()) if n in old_ids} == old_ids


def test_broken_json_blocks_and_keeps_db(session, paths):
    populate(session)
    sync.export_to_disk(session)
    (paths / "data.json").write_text("<<<<<<< HEAD\n{}\n=======\n", encoding="utf-8")
    with pytest.raises(sync.SyncError, match="合併衝突"):
        sync.check(session)
    assert sync.status.error
    assert len(session.exec(select(Hero)).all()) == 3


def test_missing_json_is_created_from_db(session, paths):
    populate(session)
    assert not (paths / "data.json").exists()
    assert sync.check(session) is False
    assert (paths / "data.json").exists()


def test_export_without_changes_keeps_file(session, paths):
    populate(session)
    sync.export_to_disk(session)
    first = (paths / "data.json").read_bytes()
    sync.export_to_disk(session)
    assert (paths / "data.json").read_bytes() == first
    repo.set_counter(session, *[h.id for h in session.exec(select(Hero)).all()][:2], 0)
    session.commit()
    sync.export_to_disk(session)
    assert (paths / "data.json").read_bytes() != first
