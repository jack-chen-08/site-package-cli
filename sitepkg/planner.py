"""plan 子命令：只读比对目标环境，输出新增 / 跳过 / 冲突清单。

plan 全程在 PostgreSQL 只读事务（SET TRANSACTION READ ONLY）内执行，
即使代码有误，数据库也会拒绝任何写入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, text

from .db import readonly_connection

#: apply/plan 的依赖顺序（site 必须最先，其余按引用链排列）
STAGE_ORDER: tuple[str, ...] = (
    "site",
    "spaces",
    "role_bindings",
    "sop_template_enables",
    "kb_scopes",
    "price_book",
    "miniapp_config",
)

STAGE_LABEL = {
    "site": "站点",
    "spaces": "空间",
    "role_bindings": "角色绑定",
    "sop_template_enables": "SOP 模板启用",
    "kb_scopes": "知识库范围",
    "price_book": "价目",
    "miniapp_config": "小程序配置",
}

#: 各阶段业务主键（用于幂等定位）
KEY_FIELDS: dict[str, tuple[str, ...]] = {
    "site": (),
    "spaces": ("space_code",),
    "role_bindings": ("role_code", "permission_template_code"),
    "sop_template_enables": ("template_code", "template_version"),
    "kb_scopes": ("kb_code",),
    "price_book": ("item_code",),
    "miniapp_config": (),
}

#: 各阶段参与比对的字段
COMPARE_FIELDS: dict[str, tuple[str, ...]] = {
    "site": ("name", "timezone", "locale", "status", "contact", "branding"),
    "spaces": ("name", "capacity", "reservation_rule_code", "enabled"),
    "role_bindings": ("role_name", "permission_template_code", "scope"),
    "sop_template_enables": ("enabled", "channel"),
    "kb_scopes": ("name", "visibility", "space_codes"),
    "price_book": ("name", "unit_amount_fen", "currency", "billing_period", "tax_included"),
    "miniapp_config": ("app_id", "name", "entry_path", "theme_color", "features"),
}

CREATE, SKIP, CONFLICT = "create", "skip", "conflict"


@dataclass(frozen=True)
class Entity:
    """包内一个待落库对象（data 的键已对齐一期表列名）。"""

    stage: str
    key: str
    label: str
    data: dict[str, Any]


@dataclass
class PlanItem:
    stage: str
    key: str
    action: str
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "stage": self.stage,
            "stage_label": STAGE_LABEL[self.stage],
            "key": self.key,
            "action": self.action,
            "reason": self.reason,
        }


@dataclass
class PlanResult:
    package_dir: str
    org_code: str
    site_code: str
    package_version: str
    applied: bool = False
    managed: bool = False
    items: list[PlanItem] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {CREATE: 0, SKIP: 0, CONFLICT: 0})

    @property
    def has_conflict(self) -> bool:
        return self.counts[CONFLICT] > 0

    def rows(self) -> list[list[str]]:
        return [[STAGE_LABEL[i.stage], i.key, i.action, i.reason] for i in self.items]

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": "plan",
            "package": self.package_dir,
            "site": {
                "org_code": self.org_code,
                "site_code": self.site_code,
                "package_version": self.package_version,
            },
            "dry_run": True,
            "already_applied": self.applied,
            "managed_by_package": self.managed,
            "counts": dict(self.counts),
            "total": len(self.items),
            "items": [i.to_dict() for i in self.items],
        }


def build_entities(pkg: dict[str, Any]) -> dict[str, list[Entity]]:
    """把 8 个文件规范化成按阶段分组的实体列表（列名对齐一期表）。"""
    site = pkg["site"]
    currency = pkg["price_book"]["currency"]
    mini = pkg["miniapp_config"]

    entities: dict[str, list[Entity]] = {stage: [] for stage in STAGE_ORDER}
    entities["site"] = [
        Entity(
            stage="site",
            key=site["site_code"],
            label=site["name"],
            data={
                "org_code": site["org_code"],
                "site_code": site["site_code"],
                "name": site["name"],
                "timezone": site["timezone"],
                "locale": site["locale"],
                "status": site["status"],
                "contact": site["contact"],
                "branding": site["branding"],
            },
        )
    ]
    for sp in pkg["spaces"]["spaces"]:
        entities["spaces"].append(
            Entity(
                stage="spaces",
                key=sp["space_code"],
                label=sp["name"],
                data={
                    "space_code": sp["space_code"],
                    "name": sp["name"],
                    "capacity": sp["capacity"],
                    "reservation_rule_code": sp["reservation_rule_code"],
                    "enabled": sp["enabled"],
                },
            )
        )
    for rb in pkg["role_bindings"]["role_bindings"]:
        entities["role_bindings"].append(
            Entity(
                stage="role_bindings",
                key=f"{rb['role_code']}:{rb['permission_template_code']}",
                label=rb["role_name"],
                data={
                    "role_code": rb["role_code"],
                    "role_name": rb["role_name"],
                    "permission_template_code": rb["permission_template_code"],
                    "scope": rb["scope"],
                },
            )
        )
    for sop in pkg["sop_templates"]["sop_templates"]:
        entities["sop_template_enables"].append(
            Entity(
                stage="sop_template_enables",
                key=f"{sop['template_code']}@{sop['version']}",
                label=sop["template_code"],
                data={
                    "template_code": sop["template_code"],
                    "template_version": sop["version"],
                    "enabled": sop["enabled"],
                    "channel": sop["channel"],
                },
            )
        )
    for kb in pkg["kb_scopes"]["kb_scopes"]:
        entities["kb_scopes"].append(
            Entity(
                stage="kb_scopes",
                key=kb["kb_code"],
                label=kb["name"],
                data={
                    "kb_code": kb["kb_code"],
                    "name": kb["name"],
                    "visibility": kb["visibility"],
                    "space_codes": list(kb["space_codes"]),
                },
            )
        )
    for item in pkg["price_book"]["price_items"]:
        entities["price_book"].append(
            Entity(
                stage="price_book",
                key=item["item_code"],
                label=item["name"],
                data={
                    "item_code": item["item_code"],
                    "name": item["name"],
                    "unit_amount_fen": item["unit_amount_fen"],
                    "currency": currency,
                    "billing_period": item["billing_period"],
                    "tax_included": item["tax_included"],
                },
            )
        )
    entities["miniapp_config"] = [
        Entity(
            stage="miniapp_config",
            key=mini["app_id"],
            label=mini["name"],
            data={
                "app_id": mini["app_id"],
                "name": mini["name"],
                "entry_path": mini["entry_path"],
                "theme_color": mini["theme_color"],
                "features": mini["features"],
            },
        )
    ]
    return entities


def _select_stage(conn, stage: str, site_id) -> dict[tuple, dict[str, Any]]:
    cols = KEY_FIELDS[stage] + COMPARE_FIELDS[stage]
    sql = f"SELECT {', '.join(cols)} FROM {stage} WHERE site_id = :site_id"
    rows = conn.execute(text(sql), {"site_id": site_id}).mappings().all()
    out: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = tuple(row[f] for f in KEY_FIELDS[stage])
        out[key] = dict(row)
    return out


def _key_of(stage: str, data: dict[str, Any]) -> tuple:
    return tuple(data[f] for f in KEY_FIELDS[stage])


def _diff_fields(stage: str, existing: dict[str, Any], data: dict[str, Any]) -> list[str]:
    changed = []
    for f in COMPARE_FIELDS[stage]:
        if existing.get(f) != data.get(f):
            changed.append(f)
    return changed


def plan_package(pkg: dict[str, Any], engine: Engine, package_dir: str = "") -> PlanResult:
    """只读比对，返回将要新增 / 跳过 / 冲突的对象清单。"""
    manifest = pkg["manifest"]
    org, site_code, version = manifest["org_code"], manifest["site_code"], manifest["package_version"]
    entities = build_entities(pkg)
    result = PlanResult(
        package_dir=package_dir,
        org_code=org,
        site_code=site_code,
        package_version=version,
    )

    with readonly_connection(engine) as conn:
        site_row = conn.execute(
            text(
                "SELECT id, name, timezone, locale, status, contact, branding, package_version "
                "FROM sites WHERE org_code = :org AND site_code = :site"
            ),
            {"org": org, "site": site_code},
        ).mappings().first()
        applied_versions = {
            r["package_version"]
            for r in conn.execute(
                text("SELECT package_version FROM applied_packages WHERE site_code = :s"),
                {"s": site_code},
            ).mappings()
        }
        result.managed = bool(applied_versions)
        result.applied = version in applied_versions

        # 情况 1：站点不存在 → 全部新增
        if site_row is None:
            for stage in STAGE_ORDER:
                for e in entities[stage]:
                    result.items.append(PlanItem(stage, e.key, CREATE, "目标环境不存在该对象"))
            _finish(result)
            return result

        # 情况 2：该 package_version 已应用 → 全部跳过
        if result.applied:
            for stage in STAGE_ORDER:
                for e in entities[stage]:
                    result.items.append(
                        PlanItem(stage, e.key, SKIP, f"package_version {version} 已应用（幂等键命中）")
                    )
            _finish(result)
            return result

        # 情况 3：站点存在但不由配置包管理 → 冲突
        if not result.managed:
            for stage in STAGE_ORDER:
                for e in entities[stage]:
                    result.items.append(
                        PlanItem(
                            stage,
                            e.key,
                            CONFLICT,
                            f"site_code {site_code} 已被占用且非配置包创建，需人工确认",
                        )
                    )
            _finish(result)
            return result

        # 情况 4：站点由配置包管理，按对象逐个比对（升级场景）
        site_id = site_row["id"]
        existing_by_stage = {stage: _select_stage(conn, stage, site_id) for stage in STAGE_ORDER[1:]}

        for e in entities["site"]:
            changed = _diff_fields("site", dict(site_row), e.data)
            if changed:
                result.items.append(
                    PlanItem("site", e.key, CONFLICT, f"站点字段将被更新：{', '.join(changed)}")
                )
            else:
                result.items.append(PlanItem("site", e.key, SKIP, "站点字段一致"))

        for stage in STAGE_ORDER[1:]:
            existing = existing_by_stage[stage]
            for e in entities[stage]:
                row = existing.get(_key_of(stage, e.data))
                if row is None:
                    result.items.append(PlanItem(stage, e.key, CREATE, "目标环境不存在该对象"))
                else:
                    changed = _diff_fields(stage, row, e.data)
                    if changed:
                        result.items.append(
                            PlanItem(stage, e.key, CONFLICT, f"字段将被更新：{', '.join(changed)}")
                        )
                    else:
                        result.items.append(PlanItem(stage, e.key, SKIP, "字段一致"))
    _finish(result)
    return result


def _finish(result: PlanResult) -> None:
    counts = {CREATE: 0, SKIP: 0, CONFLICT: 0}
    for item in result.items:
        counts[item.action] += 1
    result.counts = counts


__all__ = [
    "STAGE_ORDER",
    "STAGE_LABEL",
    "KEY_FIELDS",
    "COMPARE_FIELDS",
    "Entity",
    "PlanItem",
    "PlanResult",
    "build_entities",
    "plan_package",
]
