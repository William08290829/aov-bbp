"""Fetch hero avatars from the Vietnamese official site (lienquan.garena.vn).

Approach adapted from aov-scrapecore (MIT License), scrapecore/services/scraper_service.py:
the hero list page is parsed with these selectors
  hero   .st-heroes__list .st-heroes__item   (href = hero page, data-type = class ids)
  name   .st-heroes__item--name
  image  .st-heroes__item--img img[src]

Step by step (stop and review between steps):
  python scripts/fetch_avatars.py check              # fetch the list page, verify selectors
  python scripts/fetch_avatars.py map                # compare with data/name_map.csv
  python scripts/fetch_avatars.py download [--force] # download avatars for confirmed rows

Only rows of name_map.csv whose confidence is 高 are downloaded. Classes from the
Vietnamese site are never written to the database: heroes.csv is authoritative.
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from admin import db, repo, sync  # noqa: E402

LIST_URL = "https://lienquan.garena.vn/hoc-vien/tuong-skin/"
USER_AGENT = "Mozilla/5.0 (compatible; BBP-avatar-fetcher/1.0; personal non-commercial fan tool)"
NAME_MAP = db.ROOT / "data" / "name_map.csv"
CACHE = db.ROOT / "data" / ".cache" / "vn_heroes.json"
CONFIRMED = "高"
CLASS_IDS = {28: "戰士", 31: "坦克", 29: "法師", 32: "刺客", 30: "輔助", 33: "射手"}


@dataclass
class VnHero:
    vn_id: str
    vn_name: str
    href: str
    img: str
    classes: list[str]


# ---------------------------------------------------------------- parsing


class HeroListParser(HTMLParser):
    """Collects `.st-heroes__item` entries inside `.st-heroes__list`."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heroes: list[dict] = []
        self._list_depth = 0      # >0 while inside .st-heroes__list
        self._depth = 0
        self._item: dict | None = None
        self._item_depth = 0
        self._in_img_box = False
        self._in_name = False

    @staticmethod
    def _classes(attrs) -> set[str]:
        return set((dict(attrs).get("class") or "").split())

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            self._start(tag, attrs)
            return
        self._depth += 1
        self._start(tag, attrs)

    def _start(self, tag, attrs):
        cls = self._classes(attrs)
        a = dict(attrs)
        if "st-heroes__list" in cls and not self._list_depth:
            self._list_depth = self._depth
        if not self._list_depth:
            return
        if "st-heroes__item" in cls and self._item is None:
            self._item = {"href": a.get("href", ""), "type": a.get("data-type", ""), "name": "", "img": ""}
            self._item_depth = self._depth
        elif self._item is not None:
            if "st-heroes__item--img" in cls:
                self._in_img_box = True
            elif tag == "img" and self._in_img_box and not self._item["img"]:
                self._item["img"] = a.get("src") or a.get("data-src") or ""
            elif "st-heroes__item--name" in cls:
                self._in_name = True

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if self._item is not None and self._depth == self._item_depth:
            self.heroes.append(self._item)
            self._item = None
            self._in_img_box = self._in_name = False
        elif self._item is not None:
            if tag == "div":
                self._in_img_box = False
            if tag in ("h2", "h3", "span", "div", "p"):
                self._in_name = False
        if self._list_depth and self._depth == self._list_depth:
            self._list_depth = 0
        self._depth -= 1

    def handle_data(self, data):
        if self._item is not None and self._in_name:
            self._item["name"] += data


VOID_TAGS = {"img", "br", "hr", "input", "meta", "link", "source", "area", "base", "col", "embed", "wbr"}


def parse_list(html: str) -> list[VnHero]:
    parser = HeroListParser()
    parser.feed(html)
    heroes = []
    for item in parser.heroes:
        path = urlparse(item["href"]).path.rstrip("/")
        try:
            ids = json.loads(item["type"] or "[]")
        except json.JSONDecodeError:
            ids = []
        heroes.append(VnHero(
            vn_id=path.rsplit("/", 1)[-1] if path else "",
            vn_name=" ".join(item["name"].split()),
            href=item["href"],
            img=item["img"],
            classes=[CLASS_IDS.get(i, str(i)) for i in ids if isinstance(i, int)],
        ))
    return heroes


# ---------------------------------------------------------------- io helpers


def http_get(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


HEAD_IMG_RE = re.compile(r"https://lienquan\.garena\.vn/wp-content/uploads/[^\"' )]+head\.(?:jpe?g|png|webp)")


def fetch_image(source: VnHero, delay: float) -> bytes:
    """List-page image; if it is not jpg/png/webp (e.g. a GIF), fall back to the
    `*head.jpg` icon on the hero's own page."""
    data = http_get(source.img)
    if repo._sniff_image_ext(data):
        return data
    time.sleep(delay)
    page = http_get(source.href).decode("utf-8", errors="replace")
    match = HEAD_IMG_RE.search(page)
    if not match:
        raise repo.RepoError("列表頁圖片不是 jpg / png / webp，英雄頁也找不到 head 圖示")
    time.sleep(delay)
    return http_get(match.group(0))


def load_cache() -> list[VnHero]:
    if not CACHE.exists():
        sys.exit("找不到快取的英雄列表，請先執行：python scripts/fetch_avatars.py check")
    return [VnHero(**h) for h in json.loads(CACHE.read_text(encoding="utf-8"))]


def read_name_map() -> list[dict]:
    with open(NAME_MAP, encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def db_heroes() -> list[str]:
    data = sync.parse_data(db.DATA_JSON.read_bytes())
    return [h["name"] for h in data["heroes"]]


# ---------------------------------------------------------------- commands


def cmd_check(_args) -> int:
    print(f"抓取 {LIST_URL} …")
    try:
        html = http_get(LIST_URL).decode("utf-8", errors="replace")
    except OSError as e:
        print(f"錯誤：無法抓取列表頁：{e}", file=sys.stderr)
        return 1
    heroes = parse_list(html)
    problems = [h for h in heroes if not (h.vn_id and h.vn_name and h.img)]
    if not heroes:
        print("錯誤：找不到任何 .st-heroes__item，網站可能已改版，需要更新 selector。", file=sys.stderr)
        return 1

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps([asdict(h) for h in heroes], ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"抓到 {len(heroes)} 位英雄（已存到 {CACHE.relative_to(db.ROOT)}）。前 5 筆：")
    for h in heroes[:5]:
        print(f"  vn_id={h.vn_id:<14} 名稱={h.vn_name:<14} 職業={'/'.join(h.classes) or '?':<8} 頭像={h.img}")
    if problems:
        print(f"[警告] 有 {len(problems)} 筆缺少 vn_id、名稱或頭像：")
        for h in problems[:10]:
            print(f"  {asdict(h)}")
    dup = sorted({h.vn_id for h in heroes if sum(x.vn_id == h.vn_id for x in heroes) > 1})
    if dup:
        print(f"[警告] vn_id 重複：{', '.join(dup)}")
    return 0 if not problems else 2


def cmd_map(_args) -> int:
    vn = {h.vn_id: h for h in load_cache()}
    rows = read_name_map()
    names = db_heroes()
    mapped_tw = {r["tw_name"] for r in rows}
    mapped_vn = {r["vn_id"] for r in rows}

    def section(title, items):
        print(f"\n## {title}（{len(items)}）")
        for line in items:
            print(f"  {line}")

    section("對照表中 vn_id 在越南網站找不到", [
        f"{r['tw_name']} → {r['vn_id']}" for r in rows if r["vn_id"] not in vn])
    section("對照表中台服名稱不在資料庫", [r["tw_name"] for r in rows if r["tw_name"] not in names])
    dup_vn = sorted({r["vn_id"] for r in rows if sum(x["vn_id"] == r["vn_id"] for x in rows) > 1})
    section("對照表中 vn_id 重複", dup_vn)
    section("待確認（confidence 不是「高」）", [
        f"{r['tw_name']} → {r['vn_id']}（{vn[r['vn_id']].vn_name if r['vn_id'] in vn else '?'}，{r['confidence'] or '空白'}）"
        for r in rows if r["confidence"] != CONFIRMED])
    section("資料庫中有、對照表沒有", [n for n in names if n not in mapped_tw])
    section("越南網站有、對照表沒有", [
        f"{h.vn_id}（{h.vn_name}，{'/'.join(h.classes)}）" for h in vn.values() if h.vn_id not in mapped_vn])
    return 0


def cmd_download(args) -> int:
    vn = {h.vn_id: h for h in load_cache()}
    rows = [r for r in read_name_map() if r["confidence"] == CONFIRMED]
    if args.only:
        rows = [r for r in rows if r["tw_name"] in set(args.only)]

    db.init_db()
    done, skipped, failed = [], [], []
    with db.new_session() as session:
        try:
            sync.check(session)
        except sync.SyncError as e:
            print(f"錯誤：{e}", file=sys.stderr)
            return 1
        first = True
        for r in rows:
            hero = repo.get_hero_by_name(session, r["tw_name"])
            source = vn.get(r["vn_id"])
            if hero is None or source is None or not source.img:
                continue  # reported by the lists below
            if hero.avatar and (db.AVATAR_DIR / hero.avatar).exists() and not args.force:
                skipped.append(hero.name)
                continue
            if not first:
                time.sleep(args.delay)
            first = False
            try:
                data = fetch_image(source, args.delay)
                ext = repo._sniff_image_ext(data)
                if ext is None:
                    raise repo.RepoError("不是 jpg / png / webp 圖片")
                repo.save_avatar(session, hero.id, f"avatar{ext}", data)
                session.commit()
                done.append(hero.name)
                print(f"  ✓ {hero.name} ← {source.vn_name}")
            except (OSError, repo.RepoError) as e:
                session.rollback()
                failed.append(f"{hero.name}：{e}")
                print(f"  ✗ {hero.name}：{e}")
        sync.export_to_disk(session)

    all_rows = read_name_map()
    names = db_heroes()
    mapped_tw = {r["tw_name"] for r in all_rows if r["vn_id"] in vn}
    mapped_vn = {r["vn_id"] for r in all_rows}
    print(f"\n下載 {len(done)} 張，略過已有頭像 {len(skipped)} 張，失敗 {len(failed)} 張。")
    for f in failed:
        print(f"  失敗：{f}")
    unconfirmed = [r["tw_name"] for r in all_rows if r["confidence"] != CONFIRMED]
    if unconfirmed:
        print(f"未確認而未下載（{len(unconfirmed)}）：" + "、".join(unconfirmed))
    print(f"資料庫中有但對照不到（{sum(n not in mapped_tw for n in names)}）："
          + "、".join(n for n in names if n not in mapped_tw))
    print(f"越南網站有但資料庫沒有（{sum(i not in mapped_vn for i in vn)}）："
          + "、".join(f"{h.vn_name}({i})" for i, h in vn.items() if i not in mapped_vn))
    if done:
        print("頭像已存到 site/avatars/，data.json 已更新，記得 commit 並 push。")
    return 0 if not failed else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="從越南官網抓取英雄頭像")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="抓取列表頁並確認 selector 仍有效")
    sub.add_parser("map", help="比對 data/name_map.csv")
    dl = sub.add_parser("download", help="下載已確認（confidence=高）的頭像")
    dl.add_argument("--force", action="store_true", help="已有頭像也重新下載")
    dl.add_argument("--delay", type=float, default=1.5, help="每次下載之間的秒數（預設 1.5）")
    dl.add_argument("--only", nargs="+", metavar="台服名稱", help="只下載這些英雄")
    args = parser.parse_args(argv)
    return {"check": cmd_check, "map": cmd_map, "download": cmd_download}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
