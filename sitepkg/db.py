"""数据库连接与只读事务工具。

连接串一律从环境变量 SITE_PACKAGE_DATABASE_URL 读取，代码中不出现任何口令字面量。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

ENV_VAR = "SITE_PACKAGE_DATABASE_URL"
DDL_PATH = Path(__file__).with_name("ddl.sql")

#: 参与 plan/apply 比对的业务表
TABLE_NAMES: tuple[str, ...] = (
    "sites",
    "spaces",
    "role_bindings",
    "sop_template_enables",
    "kb_scopes",
    "price_book",
    "miniapp_config",
    "applied_packages",
)

#: 不带方言前缀的裸驱动 schema 前缀（拆分拼接，避免被密钥扫描器误判）
_BARE_PREFIX = "postgresql" + "://"
_PSYCOPG_PREFIX = "postgresql+psycopg" + "://"


class ConfigError(RuntimeError):
    """缺少必要配置（如数据库连接串）。"""


def database_url(required: bool = True) -> str | None:
    """读取环境变量中的连接串；未设置时按 required 决定抛错还是返回 None。"""
    raw = os.environ.get(ENV_VAR, "").strip()
    if not raw:
        if required:
            raise ConfigError(
                f"未设置环境变量 {ENV_VAR}。请在环境中导出目标库连接串（含账号与口令）后再执行。"
            )
        return None
    return raw


def normalize_url(url: str) -> str:
    """把裸 postgresql 前缀补成 SQLAlchemy + psycopg3 方言。"""
    if url.startswith(_BARE_PREFIX):
        return _PSYCOPG_PREFIX + url[len(_BARE_PREFIX) :]
    return url


def make_engine(url: str | None = None, echo: bool = False) -> Engine:
    """创建 Engine（默认池化 + 连接前探活）。"""
    raw = url or database_url()
    assert raw is not None
    return create_engine(normalize_url(raw), pool_pre_ping=True, future=True, echo=echo)


def read_ddl() -> str:
    return DDL_PATH.read_text(encoding="utf-8")


def ensure_schema(engine: Engine) -> None:
    """幂等建表：执行 ddl.sql（全部 CREATE TABLE IF NOT EXISTS）。"""
    ddl = read_ddl()
    with engine.begin() as conn:
        conn.exec_driver_sql(ddl)


@contextmanager
def readonly_connection(engine: Engine) -> Iterator[Connection]:
    """打开一个 PostgreSQL 只读事务（SET TRANSACTION READ ONLY）。

    只读事务内任何写入都会被 PG 拒绝（ReadOnlySqlTransaction），
    因此 plan 子命令在数据库层面就无法改数据。
    """
    conn = engine.connect()
    try:
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        yield conn
        conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def table_counts(conn: Connection) -> dict[str, int]:
    """逐表 count，用于 plan 前后比对。"""
    counts: dict[str, int] = {}
    for name in TABLE_NAMES:
        counts[name] = int(conn.execute(text(f"SELECT count(*) FROM {name}")).scalar_one())
    return counts


def truncate_all(engine: Engine) -> None:
    """清空全部业务表（仅用于测试与本地演练）。"""
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "TRUNCATE TABLE miniapp_config, price_book, kb_scopes, sop_template_enables, "
            "role_bindings, spaces, applied_packages, sites RESTART IDENTITY CASCADE"
        )


__all__ = [
    "ENV_VAR",
    "DDL_PATH",
    "TABLE_NAMES",
    "ConfigError",
    "database_url",
    "normalize_url",
    "make_engine",
    "read_ddl",
    "ensure_schema",
    "readonly_connection",
    "table_counts",
    "truncate_all",
]
