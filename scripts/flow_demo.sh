#!/usr/bin/env bash
# 全流程演练脚本（用于生成 RUN_LOG.md 的真实记录）
set -u
cd /home/ubuntuuser/work/ch2461
source /tmp/pgenv.sh
PY=.venv/bin/python

run() {
  echo "\$ $*"
  "$@" 2>&1
  echo "[exit=$?]"
  echo
}

echo "===== 0. 重置临时库 ====="
run $PY scripts/dev_db.py reset
run $PY scripts/dev_db.py counts

echo "===== 1. validate: 合法示例包 ====="
run $PY site_package.py validate examples/good

echo "===== 2. validate: 4 种埋错包 ====="
for p in bad_schema bad_ref bad_amount; do
  run $PY site_package.py validate "examples/$p" --json
done
run $PY scripts/dev_db.py seed-conflict
run $PY site_package.py validate examples/bad_conflict

echo "===== 3. plan: 只读预演 ====="
run $PY site_package.py plan examples/good
run $PY scripts/dev_db.py counts

echo "===== 4. apply: 首次应用 ====="
run $PY site_package.py apply examples/good
run $PY scripts/dev_db.py counts

echo "===== 5. apply: 重复应用（幂等） ====="
run $PY site_package.py apply examples/good --json
run $PY scripts/dev_db.py counts

echo "===== 6. apply: 中途失败回滚演练（fail-at price_book） ====="
rm -rf /tmp/pkg_fail
cp -r examples/good /tmp/pkg_fail
sed -i 's/SITE_DEMO_ALPHA/SITE_DEMO_BETA/g' /tmp/pkg_fail/*.json
run $PY site_package.py apply /tmp/pkg_fail --fail-at price_book --json
run $PY scripts/dev_db.py counts

echo "===== 7. 清理 ====="
rm -rf /tmp/pkg_fail
