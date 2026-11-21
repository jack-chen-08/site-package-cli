#!/usr/bin/env python3
"""本地演练辅助脚本：建表 / 清库 / 预置冲突站点 / 查看各表行数。

仅用于临时 PostgreSQL 与测试环境，不参与生产流程。
用法：
    .venv/bin/python scripts/dev_db.py init
    .venv/bin/python scripts/dev_db.py reset
    .venv/bin/python scripts/dev_db.py seed-conflict
    .venv/bin/python scripts/dev_db.py counts
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from sitepkg.db import ensure_schema, make_engine, table_counts, truncate_all  # noqa: E402

CONFLICT_ORG = "ORG_DEMO_0001"
CONFLICT_SITE = "SITE_DEMO_CONFLICT"


def main(argv: list[str]) -> int:
    action = argv[1] if len(argv) > 1 else "counts"
    engine = make_engine()

    if action == "init":
        ensure_schema(engine)
        print("已按 sitepkg/ddl.sql 建表（IF NOT EXISTS，可重复执行）")
    elif action == "reset":
        truncate_all(engine)
        print("已清空全部业务表")
    elif action == "seed-conflict":
        ensure_schema(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sites (org_code, site_code, name, timezone, locale, status, "
                    "contact, branding, package_version) "
                    "VALUES (:org, :site, '预置占用站点（虚构）', 'Asia/Shanghai', 'zh-CN', 'active', "
                    "'{}'::jsonb, '{}'::jsonb, NULL) "
                    "ON CONFLICT (org_code, site_code) DO NOTHING"
                ),
                {"org": CONFLICT_ORG, "site": CONFLICT_SITE},
            )
        print(f"已预置占用站点 {CONFLICT_ORG} / {CONFLICT_SITE}")
    elif action == "counts":
        with engine.connect() as conn:
            for name, count in table_counts(conn).items():
                print(f"{name:24s} {count}")
    else:
        print(f"未知动作：{action}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
