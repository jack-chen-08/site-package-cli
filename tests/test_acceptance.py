"""验收测试：对应任务书 3 条验收 + Schema 固化检查。

验收 1：示例包 validate 通过；4 种埋错包分别报出对应错误。
验收 2：plan 前后各表行数不变。
验收 3：apply 中途失败整体回滚无残留；同包重复 apply 不产生重复记录并提示「已应用」。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from sitepkg.applier import apply_package
from sitepkg.db import TABLE_NAMES, readonly_connection, table_counts
from sitepkg.planner import plan_package
from sitepkg.validator import FILES, SCHEMA_DIR, load_package, validate_package

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "site_package.py"


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _codes(result) -> list[str]:
    return [i.code for i in result.errors]


def _counts(engine) -> dict[str, int]:
    with engine.connect() as conn:
        return table_counts(conn)


def _run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=str(ROOT),
        env=merged,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _seed_conflict_site(engine, org: str = "ORG_DEMO_0001", site: str = "SITE_DEMO_CONFLICT") -> None:
    """模拟一期已存在同 org 同 site_code 的站点（占用冲突）。"""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sites (org_code, site_code, name, timezone, locale, status, "
                "contact, branding, package_version) VALUES "
                "(:org, :site, '预置占用站点（虚构）', 'Asia/Shanghai', 'zh-CN', 'active', "
                "'{}'::jsonb, '{}'::jsonb, NULL)"
            ),
            {"org": org, "site": site},
        )


# --------------------------------------------------------------------------- #
# 验收 1：validate
# --------------------------------------------------------------------------- #
def test_acceptance1_good_package_validate_passes(empty_db, examples):
    """示例包 validate 通过（结构 0 错误、引用 0 错误、site_code 未被占用）。"""
    result = validate_package(examples / "good", engine=empty_db)
    assert result.errors == [], [i.to_dict() for i in result.errors]
    assert result.site_code == "SITE_DEMO_ALPHA"
    assert result.org_code == "ORG_DEMO_0001"
    assert result.package_version == "2026.11.0"
    assert result.files_checked == len(FILES) == 8
    assert sum(result.object_counts.values()) == 16

    proc = _run_cli("validate", str(examples / "good"), "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["summary"]["errors"] == 0
    assert payload["ok"] is True


def test_acceptance1_bad_schema_reports_schema_error(empty_db, examples):
    """① Schema 错误：缺必填 + 字段类型错，均由 jsonschema 实际报出。"""
    result = validate_package(examples / "bad_schema", engine=empty_db)
    assert result.errors, "bad_schema 必须报错"
    assert "SCHEMA_INVALID" in _codes(result)
    hits = {(i.file, i.path) for i in result.errors}
    assert ("miniapp_config.json", "$") in hits
    assert ("spaces.json", "$.spaces[0].capacity") in hits
    detail = " ".join(i.message for i in result.errors)
    assert "entry_path" in detail and "integer" in detail

    proc = _run_cli("validate", str(examples / "bad_schema"), "--json")
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["summary"]["errors"] == 2


def test_acceptance1_bad_ref_reports_missing_reference(empty_db, examples):
    """② 跨文件引用不存在：role_bindings 引用了一期不存在的权限模板编码。"""
    result = validate_package(examples / "bad_ref", engine=empty_db)
    assert _codes(result) == ["REF_PERMISSION_TEMPLATE_MISSING"], [i.to_dict() for i in result.errors]
    issue = result.errors[0]
    assert issue.file == "role_bindings.json"
    assert issue.path == "$.role_bindings[1].permission_template_code"
    assert "PT_NOT_EXIST_9001" in issue.message

    proc = _run_cli("validate", str(examples / "bad_ref"), "--json")
    assert proc.returncode == 1
    assert "REF_PERMISSION_TEMPLATE_MISSING" in proc.stdout


def test_acceptance1_bad_ref_covers_sop_and_reservation(empty_db, examples, tmp_path):
    """② 补充：SOP 模板版本、预约规则编码的引用缺失同样被发现。"""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    for fname in FILES.values():
        (pkg / fname).write_text((examples / "good" / fname).read_text(encoding="utf-8"), encoding="utf-8")
    sop = json.loads((pkg / "sop_templates.json").read_text(encoding="utf-8"))
    sop["sop_templates"][0]["version"] = "9.9.9"
    (pkg / "sop_templates.json").write_text(json.dumps(sop, ensure_ascii=False), encoding="utf-8")
    spaces = json.loads((pkg / "spaces.json").read_text(encoding="utf-8"))
    spaces["spaces"][0]["reservation_rule_code"] = "RR_NOT_EXIST_9"
    (pkg / "spaces.json").write_text(json.dumps(spaces, ensure_ascii=False), encoding="utf-8")

    codes = _codes(validate_package(pkg, engine=empty_db))
    assert "REF_SOP_VERSION_MISSING" in codes
    assert "REF_RESERVATION_RULE_MISSING" in codes


def test_acceptance1_bad_conflict_site_code_occupied(empty_db, examples):
    """③ 冲突：库中同 org 下已存在同 site_code → validate 报 SITE_CODE_OCCUPIED。"""
    engine = empty_db
    _seed_conflict_site(engine)

    result = validate_package(examples / "bad_conflict", engine=engine)
    assert _codes(result) == ["SITE_CODE_OCCUPIED"], [i.to_dict() for i in result.errors]
    assert result.site_code == "SITE_DEMO_CONFLICT"
    assert "已被占用" in result.errors[0].message

    proc = _run_cli("validate", str(examples / "bad_conflict"), "--json")
    assert proc.returncode == 1
    assert "SITE_CODE_OCCUPIED" in proc.stdout


def test_acceptance1_bad_amount_rejects_non_integer_fen(empty_db, examples):
    """④ 金额非整数：1234.56 分必须被拒（金额一律整数分）。"""
    result = validate_package(examples / "bad_amount", engine=empty_db)
    assert _codes(result) == ["AMOUNT_NOT_INTEGER"], [i.to_dict() for i in result.errors]
    issue = result.errors[0]
    assert issue.file == "price_book.json"
    assert "1234.56" in issue.message

    proc = _run_cli("validate", str(examples / "bad_amount"), "--json")
    assert proc.returncode == 1
    assert "AMOUNT_NOT_INTEGER" in proc.stdout


# --------------------------------------------------------------------------- #
# 验收 2：plan 只读
# --------------------------------------------------------------------------- #
def test_acceptance2_plan_does_not_change_row_counts(empty_db, examples):
    """plan 前后逐表 count 完全相等，且不动 applied_packages。"""
    engine = empty_db
    pkg = load_package(examples / "good")

    before = _counts(engine)
    assert set(before) == set(TABLE_NAMES)
    assert all(v == 0 for v in before.values())

    plan = plan_package(pkg, engine, package_dir=str(examples / "good"))
    after = _counts(engine)

    assert before == after, f"plan 前后行数发生变化：{before} -> {after}"
    assert len(plan.items) == 16 - 1  # 15 个业务对象（manifest 不计）
    assert plan.counts == {"create": 15, "skip": 0, "conflict": 0}
    assert plan.to_dict()["dry_run"] is True

    # 再跑一次，仍未写入
    plan2 = plan_package(pkg, engine)
    assert _counts(engine) == before
    assert plan2.to_dict()["counts"] == plan.to_dict()["counts"]


def test_acceptance2_plan_connection_is_read_only(empty_db, examples):
    """只读事务由数据库兜底：任何写入都会被 PG 拒绝。"""
    engine = empty_db
    from sqlalchemy.exc import InternalError

    with pytest.raises(Exception) as excinfo:
        with readonly_connection(engine) as conn:
            conn.execute(
                text(
                    "INSERT INTO sites (org_code, site_code, name, timezone, locale, status) "
                    "VALUES ('ORG_RO', 'SITE_RO', '只读探针', 'Asia/Shanghai', 'zh-CN', 'active')"
                )
            )
            conn.commit()
    assert "read-only" in str(excinfo.value).lower() or isinstance(excinfo.value, InternalError)
    assert _counts(engine)["sites"] == 0


def test_acceptance2_plan_reports_skip_after_apply(empty_db, examples):
    """已应用后再次 plan：对象全部为 skip，不产生 create。"""
    engine = empty_db
    pkg = load_package(examples / "good")
    apply_package(pkg, engine)
    plan = plan_package(pkg, engine)
    assert plan.counts["create"] == 0
    assert plan.counts["skip"] == 15
    assert plan.applied is True


# --------------------------------------------------------------------------- #
# 验收 3：apply 事务与幂等
# --------------------------------------------------------------------------- #
def test_acceptance3_apply_writes_stages_in_order(empty_db, examples):
    """正常 apply：7 个阶段全部落库，行数与包内容一致。"""
    engine = empty_db
    pkg = load_package(examples / "good")
    result = apply_package(pkg, engine)

    assert result.status == "applied"
    assert result.ok is True
    assert result.total_written == 15
    expected = {
        "sites": 1,
        "spaces": 3,
        "role_bindings": 3,
        "sop_template_enables": 2,
        "kb_scopes": 2,
        "price_book": 3,
        "miniapp_config": 1,
        "applied_packages": 1,
    }
    assert _counts(engine) == expected


def test_acceptance3_apply_midway_failure_rolls_back_everything(empty_db, examples):
    """apply 在价目阶段注入真实约束错误 → 整体回滚，无任何残留数据。"""
    engine = empty_db
    pkg = load_package(examples / "good")

    result = apply_package(pkg, engine, fail_at="price_book")

    assert result.status == "failed"
    assert result.rolled_back is True
    assert result.fail_at == "price_book"
    assert "CheckViolation" in (result.error or "") or "check constraint" in (result.error or "")
    # 前 6 个阶段已写入的 14 个对象必须全部消失
    assert _counts(engine) == {name: 0 for name in TABLE_NAMES}
    assert result.counts["site"]["created"] == 1  # 事务内确实写过，只是被回滚了

    proc = _run_cli("apply", str(examples / "good"), "--fail-at", "price_book", "--json")
    assert proc.returncode == 3
    payload = json.loads(proc.stdout)
    assert payload["rolled_back"] is True
    assert _counts(engine) == {name: 0 for name in TABLE_NAMES}


def test_acceptance3_repeat_apply_is_idempotent(empty_db, examples):
    """同包重复 apply：(site_code, package_version) 幂等，不新增记录并提示「已应用」。"""
    engine = empty_db
    pkg = load_package(examples / "good")

    first = apply_package(pkg, engine)
    assert first.status == "applied"
    counts_after_first = _counts(engine)

    second = apply_package(pkg, engine)
    assert second.status == "already_applied"
    assert "已应用" in second.message
    assert second.total_written == 0
    assert _counts(engine) == counts_after_first
    assert counts_after_first["applied_packages"] == 1

    with engine.connect() as conn:
        n_sites = conn.execute(text("SELECT count(*) FROM sites")).scalar_one()
        n_spaces = conn.execute(text("SELECT count(*) FROM spaces")).scalar_one()
    assert (n_sites, n_spaces) == (1, 3)

    # CLI 侧同样以 0 退出并输出「已应用」
    proc = _run_cli("apply", str(examples / "good"), "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "already_applied"
    assert "已应用" in payload["message"]


# --------------------------------------------------------------------------- #
# Schema 固化与 CLI 输出形态
# --------------------------------------------------------------------------- #
def test_schema_files_are_frozen_draft_2020_12():
    """8 个 JSON Schema 文件齐备，且均声明 draft 2020-12。"""
    names = sorted(p.name for p in SCHEMA_DIR.glob("*.json"))
    assert names == sorted(list(FILES.values()))
    for path in SCHEMA_DIR.glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["$schema"] == "https://json-schema.org/draft/2020-12/schema", path.name
        assert doc.get("type") == "object"
        assert doc.get("additionalProperties") is False, path.name


def test_cli_prints_human_table_and_json(empty_db, examples):
    """默认输出含 ASCII 表格；--json 输出可解析的纯 JSON。"""
    table = _run_cli("plan", str(examples / "good"))
    assert table.returncode == 0, table.stderr
    assert "阶段" in table.stdout and "新增" in table.stdout

    only_json = _run_cli("plan", str(examples / "good"), "--json")
    assert only_json.returncode == 0
    payload = json.loads(only_json.stdout)
    assert payload["command"] == "plan"
    assert payload["counts"] == {"create": 15, "skip": 0, "conflict": 0}
    assert payload["dry_run"] is True
