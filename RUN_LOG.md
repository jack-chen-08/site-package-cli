# 全流程运行记录（RUN LOG）

> 环境：WSL Ubuntu / Python 3.12.13 / PostgreSQL 16（容器 `ch2461-pg`，镜像 `pgvector/pgvector:pg16`，宿主端口 55499）
> 业务对象：会员空间平台（虚构示例，全部数据为编造，不含任何客户信息）
> 连接串：仅从环境变量 `SITE_PACKAGE_DATABASE_URL` 读取（由 `scripts/pg_env.sh` 依据 `PG*` 变量拼装）
> 复现命令：`bash scripts/flow_demo.sh`

## 记录说明

1. 第 0 步清空临时库，确认 8 张表行数全为 0；
2. 第 1 步 `validate` 合法包通过（error=0）；
3. 第 2 步 4 种埋错包分别命中 ①②③④ 四类错误，退出码均为 1；其中 ③ 先由 `dev_db.py seed-conflict` 预置同 org 同 `site_code` 的站点；
4. 第 3 步 `plan` 输出新增 15 / 跳过 0 / 冲突 0，随后 `counts` 显示除预置冲突站点外各表仍为 0 —— 证明 plan 未写入；
5. 第 4 步 `apply` 首次应用，7 个阶段共写入 15 个对象 + 1 条 `applied_packages`；
6. 第 5 步 同包重复 `apply` → `status=already_applied`，消息含「已应用」，各表行数完全不变；
7. 第 6 步 用 `SITE_DEMO_BETA` 的副本包做故障演练（`--fail-at price_book`），价目阶段触发 `price_book_unit_amount_fen_check` 约束错误，前 6 个阶段已写入的 14 个对象随事务整体回滚，`counts` 与失败前一致。

## 一、完整终端记录

```text
===== 0. 重置临时库 =====
$ .venv/bin/python scripts/dev_db.py reset
已清空全部业务表
[exit=0]

$ .venv/bin/python scripts/dev_db.py counts
sites                    0
spaces                   0
role_bindings            0
sop_template_enables     0
kb_scopes                0
price_book               0
miniapp_config           0
applied_packages         0
[exit=0]

===== 1. validate: 合法示例包 =====
$ .venv/bin/python site_package.py validate examples/good
配置包目录 : examples/good
目标站点   : ORG_DEMO_0001 / SITE_DEMO_ALPHA    package_version=2026.11.0
文件 / 对象: 8 个文件 / 16 个对象
数据库检查 : 已执行（site_code 占用）

（无问题）

结论: 通过（error=0, warning=0）

--- JSON ---
{
  "command": "validate",
  "package": "examples/good",
  "ok": true,
  "site": {
    "org_code": "ORG_DEMO_0001",
    "site_code": "SITE_DEMO_ALPHA",
    "package_version": "2026.11.0"
  },
  "summary": {
    "files_checked": 8,
    "object_total": 16,
    "object_counts": {
      "manifest": 1,
      "site": 1,
      "spaces": 3,
      "role_bindings": 3,
      "sop_templates": 2,
      "kb_scopes": 2,
      "price_book": 3,
      "miniapp_config": 1
    },
    "errors": 0,
    "warnings": 0,
    "db_checked": true
  },
  "issues": []
}
[exit=0]

===== 2. validate: 4 种埋错包 =====
$ .venv/bin/python site_package.py validate examples/bad_schema --json
{
  "command": "validate",
  "package": "examples/bad_schema",
  "ok": false,
  "site": {
    "org_code": "ORG_DEMO_0001",
    "site_code": "SITE_DEMO_ALPHA",
    "package_version": "2026.11.0"
  },
  "summary": {
    "files_checked": 8,
    "object_total": 16,
    "object_counts": {
      "manifest": 1,
      "site": 1,
      "spaces": 3,
      "role_bindings": 3,
      "sop_templates": 2,
      "kb_scopes": 2,
      "price_book": 3,
      "miniapp_config": 1
    },
    "errors": 2,
    "warnings": 0,
    "db_checked": true
  },
  "issues": [
    {
      "code": "SCHEMA_INVALID",
      "severity": "error",
      "file": "miniapp_config.json",
      "path": "$",
      "message": "'entry_path' is a required property"
    },
    {
      "code": "SCHEMA_INVALID",
      "severity": "error",
      "file": "spaces.json",
      "path": "$.spaces[0].capacity",
      "message": "'40' is not of type 'integer'"
    }
  ]
}
[exit=1]

$ .venv/bin/python site_package.py validate examples/bad_ref --json
{
  "command": "validate",
  "package": "examples/bad_ref",
  "ok": false,
  "site": {
    "org_code": "ORG_DEMO_0001",
    "site_code": "SITE_DEMO_ALPHA",
    "package_version": "2026.11.0"
  },
  "summary": {
    "files_checked": 8,
    "object_total": 16,
    "object_counts": {
      "manifest": 1,
      "site": 1,
      "spaces": 3,
      "role_bindings": 3,
      "sop_templates": 2,
      "kb_scopes": 2,
      "price_book": 3,
      "miniapp_config": 1
    },
    "errors": 1,
    "warnings": 0,
    "db_checked": true
  },
  "issues": [
    {
      "code": "REF_PERMISSION_TEMPLATE_MISSING",
      "severity": "error",
      "file": "role_bindings.json",
      "path": "$.role_bindings[1].permission_template_code",
      "message": "权限模板编码 PT_NOT_EXIST_9001 在一期权限模板目录中不存在"
    }
  ]
}
[exit=1]

$ .venv/bin/python site_package.py validate examples/bad_amount --json
{
  "command": "validate",
  "package": "examples/bad_amount",
  "ok": false,
  "site": {
    "org_code": "ORG_DEMO_0001",
    "site_code": "SITE_DEMO_AMOUNT",
    "package_version": "2026.11.2"
  },
  "summary": {
    "files_checked": 8,
    "object_total": 16,
    "object_counts": {
      "manifest": 1,
      "site": 1,
      "spaces": 3,
      "role_bindings": 3,
      "sop_templates": 2,
      "kb_scopes": 2,
      "price_book": 3,
      "miniapp_config": 1
    },
    "errors": 1,
    "warnings": 0,
    "db_checked": true
  },
  "issues": [
    {
      "code": "AMOUNT_NOT_INTEGER",
      "severity": "error",
      "file": "price_book.json",
      "path": "$.price_items[0].unit_amount_fen",
      "message": "金额必须是整数分，当前值为 1234.56（1234.56 is not of type 'integer'）"
    }
  ]
}
[exit=1]

$ .venv/bin/python scripts/dev_db.py seed-conflict
已预置占用站点 ORG_DEMO_0001 / SITE_DEMO_CONFLICT
[exit=0]

$ .venv/bin/python site_package.py validate examples/bad_conflict
配置包目录 : examples/bad_conflict
目标站点   : ORG_DEMO_0001 / SITE_DEMO_CONFLICT    package_version=2026.11.1
文件 / 对象: 8 个文件 / 16 个对象
数据库检查 : 已执行（site_code 占用）

+--------------------+-------+---------------+-------------+------------------------------------------------------------------------------------------------------------------------------------------+
| 错误码             | 级别  | 文件          | 路径        | 说明                                                                                                                                     |
+--------------------+-------+---------------+-------------+------------------------------------------------------------------------------------------------------------------------------------------+
| SITE_CODE_OCCUPIED | error | manifest.json | $.site_code | site_code SITE_DEMO_CONFLICT 在组织 ORG_DEMO_0001 下已被占用（sites.id=3fee71de-c14d-4461-93e2-5c37707f1f69，当前 package_version=None） |
+--------------------+-------+---------------+-------------+------------------------------------------------------------------------------------------------------------------------------------------+

结论: 未通过（error=1, warning=0）

--- JSON ---
{
  "command": "validate",
  "package": "examples/bad_conflict",
  "ok": false,
  "site": {
    "org_code": "ORG_DEMO_0001",
    "site_code": "SITE_DEMO_CONFLICT",
    "package_version": "2026.11.1"
  },
  "summary": {
    "files_checked": 8,
    "object_total": 16,
    "object_counts": {
      "manifest": 1,
      "site": 1,
      "spaces": 3,
      "role_bindings": 3,
      "sop_templates": 2,
      "kb_scopes": 2,
      "price_book": 3,
      "miniapp_config": 1
    },
    "errors": 1,
    "warnings": 0,
    "db_checked": true
  },
  "issues": [
    {
      "code": "SITE_CODE_OCCUPIED",
      "severity": "error",
      "file": "manifest.json",
      "path": "$.site_code",
      "message": "site_code SITE_DEMO_CONFLICT 在组织 ORG_DEMO_0001 下已被占用（sites.id=3fee71de-c14d-4461-93e2-5c37707f1f69，当前 package_version=None）"
    }
  ]
}
[exit=1]

===== 3. plan: 只读预演 =====
$ .venv/bin/python site_package.py plan examples/good
配置包目录 : examples/good
目标站点   : ORG_DEMO_0001 / SITE_DEMO_ALPHA    package_version=2026.11.0
站点是否已由配置包管理 : 否    该版本是否已应用 : 否

+--------------+--------------------------------------+--------+----------------------+
| 阶段         | 对象键                               | 动作   | 说明                 |
+--------------+--------------------------------------+--------+----------------------+
| 站点         | SITE_DEMO_ALPHA                      | create | 目标环境不存在该对象 |
| 空间         | SPACE_HALL_A                         | create | 目标环境不存在该对象 |
| 空间         | SPACE_ROOM_B                         | create | 目标环境不存在该对象 |
| 空间         | SPACE_STUDIO_C                       | create | 目标环境不存在该对象 |
| 角色绑定     | ROLE_SITE_ADMIN:PT_MEMBER_MANAGE     | create | 目标环境不存在该对象 |
| 角色绑定     | ROLE_SPACE_OPERATOR:PT_SPACE_RESERVE | create | 目标环境不存在该对象 |
| 角色绑定     | ROLE_KB_EDITOR:PT_KB_PUBLISH         | create | 目标环境不存在该对象 |
| SOP 模板启用 | SOP_MEMBER_ONBOARD@1.1.0             | create | 目标环境不存在该对象 |
| SOP 模板启用 | SOP_RESERVATION_CHECKIN@2.0.0        | create | 目标环境不存在该对象 |
| 知识库范围   | KB_MEMBER_GUIDE                      | create | 目标环境不存在该对象 |
| 知识库范围   | KB_OPS_MANUAL                        | create | 目标环境不存在该对象 |
| 价目         | ITEM_HALL_HOURLY                     | create | 目标环境不存在该对象 |
| 价目         | ITEM_ROOM_MONTHLY                    | create | 目标环境不存在该对象 |
| 价目         | ITEM_KB_PACKAGE                      | create | 目标环境不存在该对象 |
| 小程序配置   | wxdem0a1b2c3d4e5f6                   | create | 目标环境不存在该对象 |
+--------------+--------------------------------------+--------+----------------------+

汇总: 新增 15 / 跳过 0 / 冲突 0（合计 15）

--- JSON ---
{
  "command": "plan",
  "package": "examples/good",
  "site": {
    "org_code": "ORG_DEMO_0001",
    "site_code": "SITE_DEMO_ALPHA",
    "package_version": "2026.11.0"
  },
  "dry_run": true,
  "already_applied": false,
  "managed_by_package": false,
  "counts": {
    "create": 15,
    "skip": 0,
    "conflict": 0
  },
  "total": 15,
  "items": [
    {
      "stage": "site",
      "stage_label": "站点",
      "key": "SITE_DEMO_ALPHA",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "spaces",
      "stage_label": "空间",
      "key": "SPACE_HALL_A",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "spaces",
      "stage_label": "空间",
      "key": "SPACE_ROOM_B",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "spaces",
      "stage_label": "空间",
      "key": "SPACE_STUDIO_C",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "role_bindings",
      "stage_label": "角色绑定",
      "key": "ROLE_SITE_ADMIN:PT_MEMBER_MANAGE",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "role_bindings",
      "stage_label": "角色绑定",
      "key": "ROLE_SPACE_OPERATOR:PT_SPACE_RESERVE",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "role_bindings",
      "stage_label": "角色绑定",
      "key": "ROLE_KB_EDITOR:PT_KB_PUBLISH",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "sop_template_enables",
      "stage_label": "SOP 模板启用",
      "key": "SOP_MEMBER_ONBOARD@1.1.0",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "sop_template_enables",
      "stage_label": "SOP 模板启用",
      "key": "SOP_RESERVATION_CHECKIN@2.0.0",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "kb_scopes",
      "stage_label": "知识库范围",
      "key": "KB_MEMBER_GUIDE",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "kb_scopes",
      "stage_label": "知识库范围",
      "key": "KB_OPS_MANUAL",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "price_book",
      "stage_label": "价目",
      "key": "ITEM_HALL_HOURLY",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "price_book",
      "stage_label": "价目",
      "key": "ITEM_ROOM_MONTHLY",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "price_book",
      "stage_label": "价目",
      "key": "ITEM_KB_PACKAGE",
      "action": "create",
      "reason": "目标环境不存在该对象"
    },
    {
      "stage": "miniapp_config",
      "stage_label": "小程序配置",
      "key": "wxdem0a1b2c3d4e5f6",
      "action": "create",
      "reason": "目标环境不存在该对象"
    }
  ]
}
[exit=0]

$ .venv/bin/python scripts/dev_db.py counts
sites                    1
spaces                   0
role_bindings            0
sop_template_enables     0
kb_scopes                0
price_book               0
miniapp_config           0
applied_packages         0
[exit=0]

===== 4. apply: 首次应用 =====
$ .venv/bin/python site_package.py apply examples/good
目标站点   : ORG_DEMO_0001 / SITE_DEMO_ALPHA    package_version=2026.11.0
状态       : applied
消息       : 应用成功：site_code=SITE_DEMO_ALPHA package_version=2026.11.0，共写入 15 个对象
内容摘要   : ac05c0717722a444…    耗时 60 ms

+--------------+------+------+------+
| 阶段         | 新增 | 更新 | 跳过 |
+--------------+------+------+------+
| 站点         |    1 |    0 |    0 |
| 空间         |    3 |    0 |    0 |
| 角色绑定     |    3 |    0 |    0 |
| SOP 模板启用 |    2 |    0 |    0 |
| 知识库范围   |    2 |    0 |    0 |
| 价目         |    3 |    0 |    0 |
| 小程序配置   |    1 |    0 |    0 |
+--------------+------+------+------+

--- JSON ---
{
  "command": "apply",
  "status": "applied",
  "ok": true,
  "message": "应用成功：site_code=SITE_DEMO_ALPHA package_version=2026.11.0，共写入 15 个对象",
  "site": {
    "org_code": "ORG_DEMO_0001",
    "site_code": "SITE_DEMO_ALPHA",
    "package_version": "2026.11.0",
    "site_id": "c2a5c452-6f26-45d0-9565-44f2a9fde2aa"
  },
  "payload_digest": "ac05c0717722a4448f2869c4f59538dd96de0fbda4a24ebcf7f1a0b8a39681f6",
  "counts": {
    "site": {
      "created": 1,
      "updated": 0,
      "skipped": 0
    },
    "spaces": {
      "created": 3,
      "updated": 0,
      "skipped": 0
    },
    "role_bindings": {
      "created": 3,
      "updated": 0,
      "skipped": 0
    },
    "sop_template_enables": {
      "created": 2,
      "updated": 0,
      "skipped": 0
    },
    "kb_scopes": {
      "created": 2,
      "updated": 0,
      "skipped": 0
    },
    "price_book": {
      "created": 3,
      "updated": 0,
      "skipped": 0
    },
    "miniapp_config": {
      "created": 1,
      "updated": 0,
      "skipped": 0
    }
  },
  "total_written": 15,
  "rolled_back": false,
  "fail_at": null,
  "error": null,
  "duration_ms": 60
}
[exit=0]

$ .venv/bin/python scripts/dev_db.py counts
sites                    2
spaces                   3
role_bindings            3
sop_template_enables     2
kb_scopes                2
price_book               3
miniapp_config           1
applied_packages         1
[exit=0]

===== 5. apply: 重复应用（幂等） =====
$ .venv/bin/python site_package.py apply examples/good --json
{
  "command": "apply",
  "status": "already_applied",
  "ok": true,
  "message": "已应用：site_code=SITE_DEMO_ALPHA package_version=2026.11.0 （幂等键命中，未写入任何数据）",
  "site": {
    "org_code": "ORG_DEMO_0001",
    "site_code": "SITE_DEMO_ALPHA",
    "package_version": "2026.11.0",
    "site_id": null
  },
  "payload_digest": "ac05c0717722a4448f2869c4f59538dd96de0fbda4a24ebcf7f1a0b8a39681f6",
  "counts": {},
  "total_written": 0,
  "rolled_back": false,
  "fail_at": null,
  "error": null,
  "duration_ms": 8
}
[exit=0]

$ .venv/bin/python scripts/dev_db.py counts
sites                    2
spaces                   3
role_bindings            3
sop_template_enables     2
kb_scopes                2
price_book               3
miniapp_config           1
applied_packages         1
[exit=0]

===== 6. apply: 中途失败回滚演练（fail-at price_book） =====
$ .venv/bin/python site_package.py apply /tmp/pkg_fail --fail-at price_book --json
{
  "command": "apply",
  "status": "failed",
  "ok": false,
  "message": "应用失败并已整体回滚（无残留数据）：IntegrityError: (psycopg.errors.CheckViolation) new row for relation \"price_book\" violates check constraint \"price_book_unit_amount_fen_check\"",
  "site": {
    "org_code": "ORG_DEMO_0001",
    "site_code": "SITE_DEMO_BETA",
    "package_version": "2026.11.0",
    "site_id": "27c1599c-27c4-4c2b-be99-4962d227ff8b"
  },
  "payload_digest": "8e633bbb4a5f657f5ee13d4a2359937b02616e25d9714686eede83a96607c2ba",
  "counts": {
    "site": {
      "created": 1,
      "updated": 0,
      "skipped": 0
    },
    "spaces": {
      "created": 3,
      "updated": 0,
      "skipped": 0
    },
    "role_bindings": {
      "created": 3,
      "updated": 0,
      "skipped": 0
    },
    "sop_template_enables": {
      "created": 2,
      "updated": 0,
      "skipped": 0
    },
    "kb_scopes": {
      "created": 2,
      "updated": 0,
      "skipped": 0
    },
    "price_book": {
      "created": 3,
      "updated": 0,
      "skipped": 0
    }
  },
  "total_written": 14,
  "rolled_back": true,
  "fail_at": "price_book",
  "error": "IntegrityError: (psycopg.errors.CheckViolation) new row for relation \"price_book\" violates check constraint \"price_book_unit_amount_fen_check\"\nDETAIL:  Failing row contains (4a4de5aa-2be0-49c1-8636-47308b8130c4, 27c1599c-27c4-4c2b-be99-4962d227ff8b, SIMULATED_FAILURE, 故障演练占位, -1, CNY, once, t, 2026-11-21 12:23:14.92378+00, 2026-11-21 12:23:14.92378+00).\n[SQL: INSERT INTO price_book (site_id, item_code, name, unit_amount_fen, currency, billing_period, tax_included) VALUES (%(site_id)s::UUID, %(item_code)s::VARCHAR, %(name)s::VARCHAR, %(unit_amount_fen)s::BIGINT, %(currency)s::VARCHAR, %(billing_period)s::VARCHAR, %(tax_included)s) RETURNING price_book.id, price_book.created_at, price_book.updated_at]\n[parameters: {'site_id': UUID('27c1599c-27c4-4c2b-be99-4962d227ff8b'), 'item_code': 'SIMULATED_FAILURE', 'name': '故障演练占位', 'unit_amount_fen': -1, 'currency': 'CNY', 'billing_period': 'once', 'tax_included': True}]\n(Background on this error at: https://sqlalche.me/e/21/gkpj)",
  "duration_ms": 52
}
[exit=3]

$ .venv/bin/python scripts/dev_db.py counts
sites                    2
spaces                   3
role_bindings            3
sop_template_enables     2
kb_scopes                2
price_book               3
miniapp_config           1
applied_packages         1
[exit=0]

===== 7. 清理 =====
```

## 二、pytest 运行结果（`run_tests_output.txt` 原文）

```text
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.2.0, pluggy-1.7.0 -- /home/ubuntuuser/work/ch2461/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/ubuntuuser/work/ch2461
collecting ... collected 14 items

tests/test_acceptance.py::test_acceptance1_good_package_validate_passes PASSED [  7%]
tests/test_acceptance.py::test_acceptance1_bad_schema_reports_schema_error PASSED [ 14%]
tests/test_acceptance.py::test_acceptance1_bad_ref_reports_missing_reference PASSED [ 21%]
tests/test_acceptance.py::test_acceptance1_bad_ref_covers_sop_and_reservation PASSED [ 28%]
tests/test_acceptance.py::test_acceptance1_bad_conflict_site_code_occupied PASSED [ 35%]
tests/test_acceptance.py::test_acceptance1_bad_amount_rejects_non_integer_fen PASSED [ 42%]
tests/test_acceptance.py::test_acceptance2_plan_does_not_change_row_counts PASSED [ 50%]
tests/test_acceptance.py::test_acceptance2_plan_connection_is_read_only PASSED [ 57%]
tests/test_acceptance.py::test_acceptance2_plan_reports_skip_after_apply PASSED [ 64%]
tests/test_acceptance.py::test_acceptance3_apply_writes_stages_in_order PASSED [ 71%]
tests/test_acceptance.py::test_acceptance3_apply_midway_failure_rolls_back_everything PASSED [ 78%]
tests/test_acceptance.py::test_acceptance3_repeat_apply_is_idempotent PASSED [ 85%]
tests/test_acceptance.py::test_schema_files_are_frozen_draft_2020_12 PASSED [ 92%]
tests/test_acceptance.py::test_cli_prints_human_table_and_json PASSED    [100%]

============================== 14 passed in 8.84s ==============================
```

## 三、结论

- 3 条验收全部由 pytest 覆盖并通过（14 passed）：
  - 验收 1 → `test_acceptance1_good_package_validate_passes`、`test_acceptance1_bad_schema_reports_schema_error`、`test_acceptance1_bad_ref_reports_missing_reference`、`test_acceptance1_bad_ref_covers_sop_and_reservation`、`test_acceptance1_bad_conflict_site_code_occupied`、`test_acceptance1_bad_amount_rejects_non_integer_fen`
  - 验收 2 → `test_acceptance2_plan_does_not_change_row_counts`、`test_acceptance2_plan_connection_is_read_only`、`test_acceptance2_plan_reports_skip_after_apply`
  - 验收 3 → `test_acceptance3_apply_writes_stages_in_order`、`test_acceptance3_apply_midway_failure_rolls_back_everything`、`test_acceptance3_repeat_apply_is_idempotent`
- `plan` 的只读性有双重保障：命令行层不开写事务 + 数据库层 `SET TRANSACTION READ ONLY`（写入会被 PG 直接拒绝，见 `test_acceptance2_plan_connection_is_read_only`）。
- `apply` 的原子性由单事务 + 真实约束错误验证，回滚后无任何残留行。
