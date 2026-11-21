# 会员空间平台 · 配置包 CLI（S6-PLAN-006）

一个把「会员空间平台」站点配置以**配置包**形式校验、预演、落库的命令行工具。
示例数据全部为虚构（`ORG_DEMO_0001 / SITE_DEMO_ALPHA`），不含任何客户信息。

```
validate → 结构 + 引用 + 占用三重校验
plan     → 只读比对目标环境，输出「将新增 / 跳过 / 冲突」清单
apply    → 单事务按依赖顺序写入，失败整体回滚，幂等可重放
```

---

## 1. 目录结构

```
ch2461/
├── site_package.py            # CLI 入口（click），validate / plan / apply
├── sitepkg/
│   ├── __init__.py
│   ├── validator.py           # JSON Schema + 跨文件引用 + site_code 占用
│   ├── planner.py             # 只读比对，产出 PlanResult
│   ├── applier.py             # 单事务写入 + 幂等键 + 故障注入
│   ├── db.py                  # 连接串读取、只读事务、建表、逐表 count
│   ├── models.py              # SQLAlchemy 2.0 ORM 映射
│   ├── ddl.sql                # 一期「已存在」的最小表结构（本单自建，代表现状）
│   └── report.py              # ASCII 表格 + JSON 双输出
├── schema/                    # 8 个 JSON Schema（draft 2020-12）
│   ├── manifest.json  site.json  spaces.json  role_bindings.json
│   ├── sop_templates.json  kb_scopes.json  price_book.json  miniapp_config.json
├── catalog/                   # 一期目录快照（虚构）：权限模板 / SOP 模板 / 预约规则
├── examples/
│   ├── good/                  # 合法示例包（7 个业务文件 + manifest）
│   ├── bad_schema/            # ① Schema 错误（缺必填 + 类型错）
│   ├── bad_ref/               # ② 跨文件引用不存在（权限模板编码）
│   ├── bad_conflict/          # ③ site_code 已被占用（需先向库中预置同 org 同 site_code）
│   └── bad_amount/            # ④ 金额非整数（1234.56 分）
├── scripts/
│   ├── pg_env.sh              # 由 PG* 变量拼出 SITE_PACKAGE_DATABASE_URL
│   ├── dev_db.py              # init / reset / seed-conflict / counts
│   └── flow_demo.sh           # 一键跑通 validate → plan → apply → 重复 apply → 回滚演练
├── tests/                     # pytest（14 个用例，覆盖 3 条验收）
├── RUN_LOG.md                 # 真实全流程终端记录
└── run_tests_output.txt       # 真实 pytest 输出
```

---

## 2. 运行方法

### 2.1 起一个临时 PostgreSQL 16

```bash
docker run -d --name ch2461-pg -e POSTGRES_PASSWORD="$PGPASSWORD" \
  -p 55499:5432 pgvector/pgvector:pg16
docker exec -e PGPASSWORD="$PGPASSWORD" ch2461-pg createdb -U postgres sitepkg
```

> 口令只从环境变量读，仓库与命令记录里都不写死。演练结束记得 `docker rm -f ch2461-pg`。

### 2.2 装依赖

```bash
python3 -m venv .venv
.venv/bin/pip install click jsonschema 'sqlalchemy>=2' 'psycopg[binary]' pytest
```

### 2.3 配置连接串

```bash
export PGPASSWORD=***            # 由你的临时库提供，不要写进仓库
source scripts/pg_env.sh         # 导出 SITE_PACKAGE_DATABASE_URL（postgresql+psycopg://...）
```

程序只认环境变量 `SITE_PACKAGE_DATABASE_URL`；未设置时 `validate --no-db` 仍可离线跑结构校验。

### 2.4 建表与运行

```bash
.venv/bin/python scripts/dev_db.py init                 # 按 sitepkg/ddl.sql 建表（幂等）

.venv/bin/python site_package.py validate examples/good
.venv/bin/python site_package.py plan     examples/good
.venv/bin/python site_package.py apply    examples/good
.venv/bin/python site_package.py apply    examples/good   # 第二次 → 「已应用」

# 只输出 JSON（便于管道 / CI 消费）
.venv/bin/python site_package.py plan examples/good --json

# 中途失败回滚演练（价目阶段注入真实约束错误）
.venv/bin/python site_package.py apply /path/to/pkg --fail-at price_book
```

一键全流程：`bash scripts/flow_demo.sh`（输出即 `RUN_LOG.md` 的正文）。

### 2.5 跑测试

```bash
export SITE_PACKAGE_DATABASE_URL=...   # 或 PGUSER/PGPASSWORD/PGHOST/PGPORT/PGDATABASE
.venv/bin/python -m pytest tests -v
```

测试用例自带建表与清表（`ensure_schema` + `TRUNCATE`），不会污染目标库之外的任何数据；
未配置连接串时数据库相关用例会 `skip` 并给出提示。

### 2.6 退出码

| 子命令 | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| `validate` | 通过 | 存在问题 | — | — | — |
| `plan` | 无冲突 | 校验未通过 | 存在冲突 | 执行错误 | — |
| `apply` | 已应用 / 已应用过 | 校验未通过 | 存在冲突 | 执行失败（已回滚） | 配置错误（缺连接串等） |

`--json` 只打印 JSON；默认先打印人可读表格，再打印 `--- JSON ---` 段落。

---

## 3. Schema 说明（S6-PLAN-006，已固化在 `schema/`）

统一 `"$schema": "https://json-schema.org/draft/2020-12/schema"`、`type: object`、
`additionalProperties: false`（多余字段直接报错），校验由 `jsonschema.Draft202012Validator`
实际执行，`FormatChecker` 参与日期等格式检查。

| 文件 | 顶层必填 | 关键约束 |
|---|---|---|
| `manifest.json` | `package_version` `org_code` `site_code` `created_at` `description` | 版本 `YYYY.MM.N`；编码 `^[A-Z][A-Z0-9_]{2,63}$` |
| `site.json` | `site_code` `org_code` `name` `timezone` `locale` `status` `contact` `branding` | 时区/语言/状态枚举；`site_code`、`org_code` 必须与 manifest 一致 |
| `spaces.json` | `spaces[]`：`space_code` `name` `capacity` `reservation_rule_code` `enabled` | `capacity` 为 `integer ≥ 1`；`space_code` 包内唯一 |
| `role_bindings.json` | `role_bindings[]`：`role_code` `role_name` `permission_template_code` `scope` | `scope ∈ {site, space}`；`role_code + permission_template_code` 包内唯一 |
| `sop_templates.json` | `sop_templates[]`：`template_code` `version` `enabled` `channel` | `version` 语义化 `x.y.z`；`channel ∈ {miniapp, web, all}` |
| `kb_scopes.json` | `kb_scopes[]`：`kb_code` `name` `visibility` `space_codes` | `visibility ∈ {site, role, public}`；`space_codes` 必须存在于 `spaces.json` |
| `price_book.json` | `currency` `price_items[]`：`item_code` `name` `unit_amount_fen` `billing_period` `tax_included` | **`unit_amount_fen` 为整数分（`type: integer`, `minimum: 0`）**，`1234.56` 直接判错 |
| `miniapp_config.json` | `app_id` `name` `entry_path` `theme_color` `features` | `app_id` 形如 `wx` 开头；`entry_path` 形如 `pages/...`；`theme_color` `#RRGGBB` |

### 三层校验（`sitepkg/validator.py`）

1. **结构层**：8 个文件逐个过 Schema，报 `SCHEMA_INVALID`（带 `file` + JSON Pointer `path`）；
   金额字段（`*_fen`）的类型错误单独归为 `AMOUNT_NOT_INTEGER`，便于运维一眼定位。
2. **引用层**（跨文件，依赖 `catalog/` 中的一期目录快照）：
   - `REF_PERMISSION_TEMPLATE_MISSING`：权限模板编码不存在；
   - `REF_SOP_TEMPLATE_MISSING` / `REF_SOP_VERSION_MISSING`：SOP 模板编码或版本不存在；
   - `REF_RESERVATION_RULE_MISSING`：预约规则编码不存在；
   - `REF_SPACE_MISSING`：知识库范围引用了包内不存在的空间；
   - `DUPLICATE_KEY`：包内编码重复；
   - `CODE_MISMATCH`：`site.json` 与 manifest 的 `org_code/site_code` 不一致。
3. **数据层**：查 `sites` 判断 `site_code` 是否已被该 org 占用 → `SITE_CODE_OCCUPIED`。
   若占用者正是**同一 `site_code + package_version` 且已在 `applied_packages` 登记**，
   则降级为 warning `ALREADY_APPLIED`（重复 apply 的正常路径），不阻断执行。

---

## 4. 与一期的对接点

`ddl.sql` 只包含本单依赖的**最小表结构**，代表一期已存在的表；真实落地时以一期实际迁移为准，
对接点如下（字段名即契约）：

| 配置包文件 | 目标表 | 唯一键（幂等粒度） | 说明 |
|---|---|---|---|
| `manifest.json` | `sites` | `(org_code, site_code)` | 写入 `package_version` 作为「当前由哪个包版本管理」 |
| `spaces.json` | `spaces` | `(site_id, space_code)` | 需 `site_id` 外键，故必须在 site 之后 |
| `role_bindings.json` | `role_bindings` | `(site_id, role_code, permission_template_code)` | 权限模板编码引用一期模板目录 |
| `sop_templates.json` | `sop_template_enables` | `(site_id, template_code, template_version)` | 「启用」关系，不复制模板本体 |
| `kb_scopes.json` | `kb_scopes` | `(site_id, kb_code)` | `space_codes` 以 jsonb 保存 |
| `price_book.json` | `price_book` | `(site_id, item_code)` | `unit_amount_fen bigint` + `CHECK (>= 0)` |
| `miniapp_config.json` | `miniapp_config` | `(site_id)` | 一站点一条 |
| （工具自身） | `applied_packages` | `(org_code, site_code, package_version)` | 幂等台账：`payload_digest`、`applied_at`、耗时 |

其它对接约定：

- 所有表统一含 `id uuid default gen_random_uuid()`、`created_at`、`updated_at`；
  写入走 SQLAlchemy ORM，`updated_at` 由 ORM `onupdate` 维护。
- 一期目录（权限模板 / SOP 模板版本 / 预约规则）通过 `catalog/*.json` 快照注入，
  生产可替换为直接查一期目录表：`--catalog <dir>` 或改 `PackageValidator(catalog_dir=...)`。
- `plan` 比对时只读取上述 8 张表，不触碰其它业务表。

---

## 5. 幂等与回滚机制

### 5.1 幂等

- 幂等键 **`(org_code, site_code, package_version)`**，持久化在 `applied_packages`，
  并有 `UNIQUE` 约束兜底。
- `apply` 事务一开始就 `SELECT pg_advisory_xact_lock(hashtext('sitepkg:org:site'))`，
  同一站点的并发 apply 被串行化，避免「双写」竞态。
- 命中幂等键 → 立即返回 `status=already_applied`，消息为
  「已应用：site_code=… package_version=… （幂等键命中，未写入任何数据）」，退出码 0。
- 未命中时，各阶段按唯一键做 **upsert 语义**：存在且字段一致 → `skip`；
  存在但字段不同 → `update`；不存在 → `create`。因此同版本重放不产生重复行。
- `payload_digest`（包内容 SHA-256）写入台账，便于核对「同一版本是否被换过内容」。

### 5.2 回滚

- 全流程共用**一个** `Session` 事务，按依赖顺序写入：
  `site → spaces → role_bindings → sop_template_enables → kb_scopes → price_book → miniapp_config`，
  最后写 `applied_packages`，然后统一 `commit`。
- 任一步抛异常 → `rollback()`，并返回 `status=failed / rolled_back=true` 与原始错误摘要（退出码 3）。
  已写入的前序阶段（含 `sites` 行）全部消失，不留半成品。
- `--fail-at <stage>` 是**故障演练**开关：在指定阶段插入一条必然违反数据库约束的记录
  （当前为价目阶段写入 `unit_amount_fen = -1`，触发 `price_book_unit_amount_fen_check`），
  用真实数据库错误验证回滚路径，而不是 mock。
- `plan` 的只读性同样是双保险：连接层 `SET TRANSACTION READ ONLY`，数据库层拒绝任何写入
  （`test_acceptance2_plan_connection_is_read_only` 直接断言 PG 报 read-only 错误）。

---

## 6. 测试与验收对应

| 验收 | 测试函数 |
|---|---|
| 1 · 示例包通过 + 4 种埋错包报对应错误 | `test_acceptance1_good_package_validate_passes`、`test_acceptance1_bad_schema_reports_schema_error`、`test_acceptance1_bad_ref_reports_missing_reference`、`test_acceptance1_bad_ref_covers_sop_and_reservation`、`test_acceptance1_bad_conflict_site_code_occupied`、`test_acceptance1_bad_amount_rejects_non_integer_fen` |
| 2 · plan 前后逐表 count 不变 | `test_acceptance2_plan_does_not_change_row_counts`、`test_acceptance2_plan_connection_is_read_only`、`test_acceptance2_plan_reports_skip_after_apply` |
| 3 · 中途失败整体回滚 + 重复 apply 幂等 | `test_acceptance3_apply_writes_stages_in_order`、`test_acceptance3_apply_midway_failure_rolls_back_everything`、`test_acceptance3_repeat_apply_is_idempotent` |
| Schema 固化 / CLI 双输出 | `test_schema_files_are_frozen_draft_2020_12`、`test_cli_prints_human_table_and_json` |

真实输出见 `run_tests_output.txt` 与 `RUN_LOG.md`。

---

## 7. 已知限制

1. **只做「新增/更新/跳过」，不做删除**：包中移除的对象不会从目标环境回收，
   需要人工或后续「差异清理」功能处理（避免误删线上数据）。
2. **冲突判定较保守**：`site_code` 被非本包版本占用时一律判冲突、不自动接管；
   升级场景（同 site 换 `package_version`）目前需人工确认后由运维处理。
3. **`plan` 的「冲突」粒度较粗**：既包含「站点被非本包占用」，也包含「已管理站点的字段差异」
   （会列出差异字段名），但不区分危险等级，也不提供自动升级方案；子对象新增则显示为 `create`。
4. **一期目录是快照**：`catalog/*.json` 为虚构快照，真实环境应改为查一期目录表，否则会漏检新模板。
5. **`--fail-at` 仅用于演练**，生产不应传入；它依赖 `price_book` 的 CHECK 约束存在。
6. **未做权限/审计**：谁执行了 apply 仅记录在 `applied_packages` 的时间与摘要里，未接统一审计。
7. **并发**以 advisory lock 串行化到站点粒度，超大包（数千对象）时单事务耗时较长，
   极端情况下会拉长锁等待。
8. 金额仅支持整数分（不接受浮点/字符串），跨币种只白名单了 `CNY`。
