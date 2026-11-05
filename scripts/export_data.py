"""Export the database to site/data/data.json.

The admin already exports after every change, so this is mainly a check:
it first picks up external changes to data.json (e.g. git pull) so a stale
database can never overwrite newer data, then writes the file if needed.

Usage: python scripts/export_data.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from admin import db, sync  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    db.init_db()
    with db.new_session() as session:
        try:
            result = sync.export_now(session)
        except sync.SyncError as e:
            print(f"錯誤：{e}\n請先修正 site/data/data.json 再執行。", file=sys.stderr)
            return 1

    s = result.summary
    rel = db.DATA_JSON.relative_to(db.ROOT) if db.DATA_JSON.is_relative_to(db.ROOT) else db.DATA_JSON
    if result.changed:
        print(f"已匯出 {rel}")
    else:
        print(f"{rel} 已是最新，內容沒有變更")
    print(f"英雄 {s['heroes']} 隻、剋制 {s['counters']} 筆、搭配 {s['synergies']} 筆（資料時間 {s['exported_at']}）")
    print("記得 commit 並 push。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
