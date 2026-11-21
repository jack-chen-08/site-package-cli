#!/usr/bin/env bash
# 从 PG* 环境变量拼出 SITE_PACKAGE_DATABASE_URL（口令只从环境读取，仓库内不存任何口令）。
#
# 用法示例：
#   PGPASSWORD=<临时库口令> source scripts/pg_env.sh
#   .venv/bin/python site_package.py plan examples/good
set -euo pipefail

: "${PGPASSWORD:?请先通过环境变量 PGPASSWORD 提供临时库口令}"

export PGUSER="${PGUSER:-postgres}"
export PGHOST="${PGHOST:-127.0.0.1}"
export PGPORT="${PGPORT:-55499}"
export PGDATABASE="${PGDATABASE:-sitepkg}"
export SITE_PACKAGE_DATABASE_URL="$(
  printf 'postgresql+psycopg://%s:%s@%s:%s/%s' "$PGUSER" "$PGPASSWORD" "$PGHOST" "$PGPORT" "$PGDATABASE"
)"
export SITE_PACKAGE_DATABASE_URL
