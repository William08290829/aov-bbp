"""Rebuild the database from a data.json file (restore).

Normally unnecessary: the admin re-imports site/data/data.json automatically
when it changes. Use this to restore from another file (e.g. an older copy
taken from git history) or to rebuild a broken local database.

Usage:
  python scripts/import_data.py                  # rebuild from site/data/data.json
  python scripts/import_data.py backup.json      # restore from another file;
                                                 # site/data/data.json is overwritten
  python scripts/import_data.py --reset          # also drop and recreate all tables
  python scripts/import_data.py --yes            # skip the confirmation prompt
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import SQLModel  # noqa: E402

from admin import db, sync  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="從 data.json 重建資料庫")
    parser.add_argument("source", nargs="?", type=Path, help="要匯入的檔案（預設 site/data/data.json）")
    parser.add_argument("--reset", action="store_true", help="刪除並重建所有資料表（請先停止後台）")
    parser.add_argument("-y", "--yes", action="store_true", help="不詢問直接執行")
    args = parser.parse_args(argv)

    source: Path = (args.source or db.DATA_JSON).resolve()
    if not source.exists():
        print(f"錯誤：找不到 {source}", file=sys.stderr)
        return 1
    try:
        data = sync.parse_data(source.read_bytes())
    except sync.SyncError as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1

    s = sync.summarize(data)
    other_file = source != db.DATA_JSON.resolve()
    print(f"來源：{source}")
    print(f"內容：英雄 {s['heroes']} 隻、剋制 {s['counters']} 筆、搭配 {s['synergies']} 筆（資料時間 {s['exported_at']}）")
    print("資料庫中現有的英雄、分路、剋制、搭配與設定將全部被取代。")
    if other_file:
        print(f"同時會覆寫 {db.DATA_JSON}（之後請 commit）。")
    if args.reset:
        print("--reset：會刪除並重建所有資料表，請先停止後台（uvicorn）。")
    if not args.yes:
        try:
            answer = input("確定要繼續嗎？輸入 y 繼續：").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("已取消。")
            return 1

    engine = db.get_engine()
    if args.reset:
        SQLModel.metadata.drop_all(engine)
    db.init_db(engine)
    with db.new_session() as session:
        result = sync.restore_from(session, source)

    print("已從檔案重建資料庫。")
    if result.changed:
        print(f"已更新 {db.DATA_JSON}，記得 commit 並 push。")
    if not args.reset:
        print("若後台正在執行，不需要重新啟動。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
