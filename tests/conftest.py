"""pytest 公共夹具。

数据库连接串一律从环境变量读取，仓库内不出现任何口令字面量：
  1. 优先使用 SITE_PACKAGE_DATABASE_URL；
  2. 未设置时用 PGUSER / PGPASSWORD / PGHOST / PGPORT / PGDATABASE 拼装
     （scripts/pg_env.sh 会导出这些变量）；
  3. 两者都没有 → 依赖数据库的用例 skip，并给出明确原因。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sitepkg.db import ENV_VAR, ensure_schema, make_engine, truncate_all  # noqa: E402


def _build_url_from_pg_vars() -> str | None:
    user = os.environ.get("PGUSER")
    host = os.environ.get("PGHOST")
    if not user or not host:
        return None
    from urllib.parse import quote_plus

    pwd = quote_plus(os.environ.get("PGPASSWORD", ""))
    port = os.environ.get("PGPORT", "5432")
    db = os.environ.get("PGDATABASE", "sitepkg")
    auth = f"{quote_plus(user)}:{pwd}" if pwd else quote_plus(user)
    return f"postgresql+psycopg://{auth}@{host}:{port}/{db}"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get(ENV_VAR, "").strip() or _build_url_from_pg_vars()
    if not url:
        pytest.skip(
            f"未配置数据库：请导出 {ENV_VAR}（或 PGUSER/PGPASSWORD/PGHOST/PGPORT/PGDATABASE）后重跑"
        )
    # 供被测代码（make_engine() 默认读环境变量）使用
    os.environ[ENV_VAR] = url
    return url


@pytest.fixture(scope="session")
def engine(database_url: str):
    eng = make_engine(database_url)
    ensure_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def empty_db(engine):
    """每个用例前后清空业务表，保证行数断言互不干扰。"""
    truncate_all(engine)
    yield engine
    truncate_all(engine)


@pytest.fixture()
def examples() -> Path:
    return ROOT / "examples"
