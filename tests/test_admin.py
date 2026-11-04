import json
import re

import pytest
from fastapi.testclient import TestClient

from admin import repo, sync
from admin.main import app

HX = {"HX-Request": "true"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 16


@pytest.fixture
def client(paths):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def two(session):
    a = repo.create_hero(session, "甲", "法師")
    b = repo.create_hero(session, "乙", "坦克")
    session.commit()
    return a.id, b.id


def data_json(paths) -> dict:
    return json.loads((paths / "data.json").read_text(encoding="utf-8"))


def test_pages_render(client, two):
    a, _ = two
    assert "BBP 後台" in client.get("/admin").text
    page = client.get(f"/admin/hero/{a}").text
    assert "分路與 tier" in page and "剋制與搭配" in page
    assert "職業僅供分類，不影響分路" in page
    assert "新增英雄" in client.get("/admin/hero/new").text
    partial = client.get(f"/admin/hero/{a}", headers=HX).text
    assert "<html" not in partial and "分路與 tier" in partial


def test_create_hero_exports(client, paths):
    r = client.post("/admin/hero", data={"name": "元流之子（射手）", "main_class": "射手"}, headers=HX)
    assert r.status_code == 204 and r.headers["HX-Redirect"].startswith("/admin/hero/")
    hero = data_json(paths)["heroes"][0]
    assert hero["name"] == "元流之子(射手)" and hero["form_group"] == "元流之子"


def test_validation_error_is_400_text(client, two):
    a, _ = two
    r = client.post(f"/admin/hero/{a}/basic", data={"name": "乙", "main_class": "法師"}, headers=HX)
    assert r.status_code == 400 and "已經有名為「乙」" in r.text


def test_lane_toggle_and_tier(client, paths, two):
    a, _ = two
    client.post(f"/admin/hero/{a}/lanes/打野", data={"enabled": "on", "tier": "T0"}, headers=HX)
    hero = next(h for h in data_json(paths)["heroes"] if h["name"] == "甲")
    assert hero["lanes"] == {"打野": None}  # newly checked lanes start unrated
    client.post(f"/admin/hero/{a}/lanes/打野", data={"enabled": "on", "tier": "T0"}, headers=HX)
    hero = next(h for h in data_json(paths)["heroes"] if h["name"] == "甲")
    assert hero["lanes"] == {"打野": "T0"}
    client.post(f"/admin/hero/{a}/lanes/打野", data={"tier": "T0"}, headers=HX)
    hero = next(h for h in data_json(paths)["heroes"] if h["name"] == "甲")
    assert hero["lanes"] == {}


def test_counter_cycle(client, paths, two):
    a, b = two
    labels = []
    values = []
    for _ in range(5):
        labels.append(client.post(f"/admin/hero/{a}/counter/{b}", headers=HX).text)
        values.append(data_json(paths)["counters"])
    counter_texts = [re.findall(r">\s*([^<>]+?)\s*</button>", html)[0] for html in labels]
    assert counter_texts == ["▲ 剋他", "▲▲ 超剋他", "▼ 被他剋", "▼▼ 被他完剋", "對位：無"]
    # stored as [a, b, v] with a < b by name ("乙" < "甲"), so signs flip
    assert values == [[["乙", "甲", -1]], [["乙", "甲", -2]], [["乙", "甲", 1]], [["乙", "甲", 2]], []]
    synergies = []
    for _ in range(3):
        client.post(f"/admin/hero/{a}/synergy/{b}", headers=HX)
        synergies.append(data_json(paths)["synergies"])
    assert synergies == [[["乙", "甲", 1]], [["乙", "甲", 2]], []]


def test_avatar_upload_and_delete(client, paths, two):
    a, _ = two
    r = client.post(f"/admin/hero/{a}/avatar", files={"file": ("x.png", PNG, "image/png")}, headers=HX)
    assert r.status_code == 200 and "/avatars/" in r.text
    assert (paths / "avatars" / "甲.png").exists()
    r = client.post(f"/admin/hero/{a}/delete", headers=HX)
    assert r.headers["HX-Redirect"] == "/admin"
    assert not (paths / "avatars" / "甲.png").exists()
    assert [h["name"] for h in data_json(paths)["heroes"]] == ["乙"]


def test_external_change_forces_refresh(client, paths, two):
    client.get("/admin")  # creates data.json
    data = data_json(paths)
    data["heroes"].append({"name": "丙", "main_class": "射手", "sub_class": None,
                           "avatar": None, "form_group": None, "lanes": {}})
    (paths / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    a, b = two
    r = client.post(f"/admin/hero/{a}/counter/{b}", headers=HX)
    assert r.status_code == 409 and r.headers.get("HX-Refresh") == "true"
    page = client.get("/admin").text
    assert "丙" in page


def test_broken_json_blocks_writes(client, paths, two):
    client.get("/admin")
    (paths / "data.json").write_text("{ broken", encoding="utf-8")
    a, b = two
    r = client.post(f"/admin/hero/{a}/counter/{b}", headers=HX)
    assert r.status_code == 409
    assert "data.json 讀取失敗" in client.get("/admin").text
    assert (paths / "data.json").read_text(encoding="utf-8") == "{ broken"
    sync.status.error = None
