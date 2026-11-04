"""Import the initial hero list from data/heroes.csv.

Existing heroes (same name) are skipped, so running this twice is safe.
Lanes, tiers, counters and synergies are entered in the admin, not here.

Usage: python scripts/import_heroes.py [path/to/heroes.csv]
"""

import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session  # noqa: E402

from admin import db, repo, sync  # noqa: E402
from admin.models import HERO_CLASSES, Hero  # noqa: E402

DEFAULT_CSV = db.ROOT / "data" / "heroes.csv"


@dataclass
class ImportReport:
    added: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_classes(name: str, raw: str, report: ImportReport) -> tuple[str, str | None, bool]:
    """Return (main_class, sub_class, needs_review) following the spec's fallback rules."""
    parts = [p.strip() for p in (raw or "").split("|") if p.strip()]
    main = parts[0] if parts else ""
    sub = parts[1] if len(parts) > 1 else None
    review = False

    if len(parts) > 2:
        report.warnings.append(f"{name}：職業超過兩個，只取前兩個（{raw}）")
        review = True

    if main not in HERO_CLASSES:
        if sub in HERO_CLASSES:
            report.warnings.append(f"{name}：主職業「{main}」不合法，改用副職業「{sub}」作為主職業")
            main, sub = sub, None
        else:
            report.warnings.append(f"{name}：主職業「{main}」不合法，主職業留空")
            main = ""
            if sub is not None:
                report.warnings.append(f"{name}：副職業「{sub}」不合法，已略過")
                sub = None
        review = True
    elif sub is not None and sub not in HERO_CLASSES:
        report.warnings.append(f"{name}：副職業「{sub}」不合法，已略過")
        sub, review = None, True
    elif sub is not None and sub == main:
        report.warnings.append(f"{name}：副職業與主職業相同（{sub}），已略過")
        sub, review = None, True

    return main, sub, review


def import_csv(session: Session, csv_path: Path) -> ImportReport:
    report = ImportReport()
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for lineno, row in enumerate(reader, start=2):
            try:
                name = repo.normalize_name(row.get("name", ""))
            except repo.RepoError as e:
                report.warnings.append(f"第 {lineno} 行：{e}，已略過")
                continue
            if repo.get_hero_by_name(session, name) is not None:
                report.skipped.append(name)
                continue
            main, sub, review = parse_classes(name, row.get("classes", ""), report)
            session.add(Hero(
                name=name,
                main_class=main,
                sub_class=sub,
                form_group=repo.derive_form_group(name),
                needs_review=review,
            ))
            session.flush()
            report.added.append(name)
            if review:
                report.review.append(name)
    repo.ensure_default_settings(session)
    return report


def main() -> None:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    db.init_db()
    with db.new_session() as session:
        # data.json is the source of truth: load it first so nothing is lost.
        try:
            sync.check(session)
        except sync.SyncError as e:
            sys.exit(f"錯誤：{e}\n請先修正 site/data/data.json 再執行。")
        report = import_csv(session, csv_path)
        session.commit()
        sync.export_to_disk(session)

    for w in report.warnings:
        print(f"[警告] {w}")
    print(f"新增 {len(report.added)} 隻英雄，略過已存在 {len(report.skipped)} 隻，待確認 {len(report.review)} 隻。")
    if report.review:
        print("待確認：" + "、".join(report.review))
    print(f"已更新 {db.DATA_JSON.relative_to(db.ROOT)}")


if __name__ == "__main__":
    main()
