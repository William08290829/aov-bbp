import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from admin import repo, sync
from admin.main import app
from admin.models import DEFAULT_SETTINGS, Hero
from scripts import export_data, import_data

HX = {"HX-Request": "true"}


def populate(session):
    a = repo.create_hero(session, "甲", "坦克")
    b = repo.create_hero(session, "乙", "射手")
    repo.set_lane(session, a.id, "輔助", True, "T1")
    repo.set_counter(session, a.id, b.id, 2)
    repo.set_synergy(session, a.id, b.id, 1)
    repo.ensure_default_settings(session)
    session.commit()
    return a, b


def read_json(paths):
    return json.loads((paths / "data.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- export_data.py


def test_export_script_writes_then_reports_unchanged(session, paths, capsys):
    populate(session)
    assert export_data.main([]) == 0
    assert "已匯出" in capsys.readouterr().out
    first = (paths / "data.json").read_bytes()

    assert export_data.main([]) == 0
    out = capsys.readouterr().out
    assert "內容沒有變更" in out and "英雄 2 隻、剋制 1 筆、搭配 1 筆" in out
    assert (paths / "data.json").read_bytes() == first


def test_export_script_never_overwrites_newer_file(session, paths):
    """A stale database must not clobber data.json that arrived via git pull."""
    populate(session)
    sync.export_to_disk(session)
    data = read_json(paths)
    data["heroes"].append({"name": "丙", "main_class": "法師", "sub_class": None,
                           "avatar": None, "form_group": None, "lanes": {}})
    (paths / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    sync.status.last_stat = None

    assert export_data.main([]) == 0
    assert "丙" in [h["name"] for h in read_json(paths)["heroes"]]


def test_export_script_fails_on_broken_file(session, paths, capsys):
    populate(session)
    sync.export_to_disk(session)
    (paths / "data.json").write_text("{oops", encoding="utf-8")
    assert export_data.main([]) == 1
    assert "data.json 不是合法的 JSON" in capsys.readouterr().err
    assert (paths / "data.json").read_text(encoding="utf-8") == "{oops"


# ---------------------------------------------------------------- import_data.py


def test_import_script_requires_confirmation(session, paths, monkeypatch):
    populate(session)
    sync.export_to_disk(session)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert import_data.main([]) == 1


def test_import_script_restores_other_file(session, paths):
    populate(session)
    sync.export_to_disk(session)
    backup = paths / "backup.json"
    data = read_json(paths)
    data["heroes"] = [h for h in data["heroes"] if h["name"] != "乙"]
    data["counters"] = data["synergies"] = []
    backup.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    assert import_data.main([str(backup), "--yes"]) == 0
    session.expire_all()
    assert [h.name for h in session.exec(select(Hero)).all()] == ["甲"]
    assert [h["name"] for h in read_json(paths)["heroes"]] == ["甲"]  # data.json overwritten
    assert sync.check(session) is False  # and the database knows it is in sync


def test_import_script_reset_rebuilds_tables(session, paths):
    a, _ = populate(session)
    sync.export_to_disk(session)
    before = sync.build_data(session)
    session.close()

    assert import_data.main(["--reset", "--yes"]) == 0
    with session.__class__(session.get_bind()) as fresh:
        after = sync.build_data(fresh)
    before.pop("exported_at"), after.pop("exported_at")
    assert after == before


def test_import_script_rejects_invalid_file(session, paths, capsys):
    bad = paths / "bad.json"
    bad.write_text(json.dumps({"heroes": [], "counters": [["甲", "乙", 1]],
                               "synergies": [], "settings": {}}), encoding="utf-8")
    assert import_data.main([str(bad), "--yes"]) == 1
    assert "不存在" in capsys.readouterr().err


# ---------------------------------------------------------------- settings


def test_set_setting_validation(session):
    repo.ensure_default_settings(session)
    assert repo.set_setting(session, "w_risk", " 1.5 ") == 1.5
    for key, raw in (("w_risk", "abc"), ("w_risk", "nan"), ("w_risk", "1000"), ("nope", "1")):
        with pytest.raises(repo.RepoError):
            repo.set_setting(session, key, raw)
    repo.reset_settings(session)
    assert repo.get_settings(session)["w_risk"] == DEFAULT_SETTINGS["w_risk"]


@pytest.fixture
def client(paths):
    with TestClient(app) as c:
        yield c


def test_settings_page_and_update(client, session, paths):
    populate(session)
    page = client.get("/admin/settings").text
    assert "被反制風險" in page and "tier 分數" in page

    r = client.post("/admin/settings/w_risk", data={"value": "1.2"}, headers=HX)
    assert r.status_code == 200 and "已儲存" in r.text and "已修改" in r.text
    assert read_json(paths)["settings"]["w_risk"] == 1.2

    r = client.post("/admin/settings/w_risk", data={"value": "x"}, headers=HX)
    assert r.status_code == 400 and "請輸入數字" in r.text

    r = client.post("/admin/settings/reset", headers=HX)
    assert "已恢復所有預設值" in r.text
    assert read_json(paths)["settings"]["w_risk"] == 0.5


def test_export_page(client, session, paths):
    populate(session)
    page = client.get("/admin/export").text
    assert "英雄" in page and "2 隻" in page and "Git 狀態" in page
    r = client.post("/admin/export", headers=HX)
    assert r.status_code == 200 and "已是最新" in r.text
