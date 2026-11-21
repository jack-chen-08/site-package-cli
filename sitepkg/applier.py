"""apply 子命令：单事务按依赖顺序写入，失败整体回滚，按 site_code+package_version 幂等。

关键机制：
  * 幂等键：(site_code, package_version) 落 applied_packages 唯一约束；
    写事务开始即取 pg_advisory_xact_lock，避免并发重复应用；
  * 顺序：site → spaces → role_bindings → sop_template_enables → kb_scopes → price_book → miniapp_config；
  * 回滚：整个流程在一个事务内，任一步抛错即 session.rollback()，无残留；
  * 故障演练：fail_at 指定阶段后注入真实数据库错误（价目阶段写负金额触发 CHECK 约束），
    用于验证「中途失败全部回滚」。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from .models import (
    AppliedPackage,
    KbScope,
    MiniappConfig,
    PriceBookItem,
    RoleBinding,
    Site,
    SopTemplateEnable,
    Space,
)
from .planner import (
    COMPARE_FIELDS,
    KEY_FIELDS,
    STAGE_LABEL,
    STAGE_ORDER,
    Entity,
    build_entities,
)

MODEL_BY_STAGE: dict[str, Any] = {
    "spaces": Space,
    "role_bindings": RoleBinding,
    "sop_template_enables": SopTemplateEnable,
    "kb_scopes": KbScope,
    "price_book": PriceBookItem,
    "miniapp_config": MiniappConfig,
}


class SimulationError(RuntimeError):
    """故障演练注入的错误。"""


@dataclass
class ApplyResult:
    status: str  # applied / already_applied / conflict / failed
    message: str
    org_code: str = ""
    site_code: str = ""
    package_version: str = ""
    site_id: str | None = None
    payload_digest: str = ""
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    fail_at: str | None = None
    error: str | None = None
    duration_ms: int = 0
    rolled_back: bool = False

    @property
    def ok(self) -> bool:
        return self.status in ("applied", "already_applied")

    @property
    def total_written(self) -> int:
        return sum(v.get("created", 0) + v.get("updated", 0) for v in self.counts.values())

    def rows(self) -> list[list[str]]:
        return [
            [
                STAGE_LABEL[stage],
                str(counts.get("created", 0)),
                str(counts.get("updated", 0)),
                str(counts.get("skipped", 0)),
            ]
            for stage, counts in self.counts.items()
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": "apply",
            "status": self.status,
            "ok": self.ok,
            "message": self.message,
            "site": {
                "org_code": self.org_code,
                "site_code": self.site_code,
                "package_version": self.package_version,
                "site_id": self.site_id,
            },
            "payload_digest": self.payload_digest,
            "counts": self.counts,
            "total_written": self.total_written,
            "rolled_back": self.rolled_back,
            "fail_at": self.fail_at,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


def package_digest(pkg: dict[str, Any]) -> str:
    """配置包内容摘要（sha256，用于记录实际应用的包内容）。"""
    canonical = json.dumps(pkg, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _same(value_a: Any, value_b: Any) -> bool:
    return value_a == value_b


def _upsert_stage(
    session: Session, stage: str, site_id, entities: list[Entity]
) -> dict[str, int]:
    """按业务主键 upsert 一个阶段的所有对象。"""
    model = MODEL_BY_STAGE[stage]
    stats = {"created": 0, "updated": 0, "skipped": 0}
    for entity in entities:
        data = dict(entity.data)
        stmt = select(model).where(model.site_id == site_id)
        for f in KEY_FIELDS[stage]:
            stmt = stmt.where(getattr(model, f) == data[f])
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            session.add(model(site_id=site_id, **data))
            stats["created"] += 1
            continue
        changed = False
        for f in COMPARE_FIELDS[stage]:
            if not _same(getattr(row, f), data.get(f)):
                setattr(row, f, data[f])
                changed = True
        if changed:
            row.updated_at = func.now()
            stats["updated"] += 1
        else:
            stats["skipped"] += 1
    return stats


def _inject_failure(session: Session, stage: str, site_id) -> None:
    """故障演练注入点。"""
    if stage == "price_book":
        # 真实数据库错误：违反 price_book.unit_amount_fen >= 0 的 CHECK 约束
        session.add(
            PriceBookItem(
                site_id=site_id,
                item_code="SIMULATED_FAILURE",
                name="故障演练占位",
                unit_amount_fen=-1,
                currency="CNY",
                billing_period="once",
                tax_included=True,
            )
        )
        session.flush()
        return
    raise SimulationError(f"故障演练：在阶段 {STAGE_LABEL[stage]} 注入失败")


def apply_package(
    pkg: dict[str, Any],
    engine: Engine,
    fail_at: str | None = None,
    package_dir: str = "",
) -> ApplyResult:
    """在单个事务内应用配置包。"""
    manifest = pkg["manifest"]
    org, site_code, version = manifest["org_code"], manifest["site_code"], manifest["package_version"]
    entities = build_entities(pkg)
    digest = package_digest(pkg)
    started = time.monotonic()

    result = ApplyResult(
        status="failed",
        message="",
        org_code=org,
        site_code=site_code,
        package_version=version,
        payload_digest=digest,
        fail_at=fail_at,
    )

    session = Session(engine)
    try:
        session.begin()
        # 并发保护：同一 site 的 apply 串行化
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"sitepkg:{org}:{site_code}"},
        )

        already = session.execute(
            select(AppliedPackage.package_version).where(
                AppliedPackage.site_code == site_code,
                AppliedPackage.package_version == version,
            )
        ).first()
        if already is not None:
            session.rollback()
            result.status = "already_applied"
            result.message = (
                f"已应用：site_code={site_code} package_version={version} "
                f"（幂等键命中，未写入任何数据）"
            )
            return result

        site = session.execute(
            select(Site).where(Site.org_code == org, Site.site_code == site_code)
        ).scalar_one_or_none()
        managed = (
            session.execute(
                select(func.count())
                .select_from(AppliedPackage)
                .where(AppliedPackage.site_code == site_code)
            ).scalar_one()
            > 0
        )

        if site is not None and not managed:
            session.rollback()
            result.status = "conflict"
            result.message = (
                f"site_code {site_code} 在组织 {org} 下已被占用且非配置包创建，"
                f"拒绝 apply（请改用新 site_code 或先人工确认归属）"
            )
            return result

        if site is None:
            site_data = entities["site"][0].data
            site = Site(**site_data, package_version=version)
            session.add(site)
            session.flush()
            result.counts["site"] = {"created": 1, "updated": 0, "skipped": 0}
        else:
            site_entity = entities["site"][0]
            changed = False
            for f in COMPARE_FIELDS["site"]:
                if not _same(getattr(site, f), site_entity.data.get(f)):
                    setattr(site, f, site_entity.data[f])
                    changed = True
            site.package_version = version
            site.updated_at = func.now()
            result.counts["site"] = {
                "created": 0,
                "updated": 1 if changed else 0,
                "skipped": 0 if changed else 1,
            }
            session.flush()

        site_id = site.id
        result.site_id = str(site_id)

        for stage in STAGE_ORDER[1:]:
            result.counts[stage] = _upsert_stage(session, stage, site_id, entities[stage])
            session.flush()
            if fail_at == stage:
                _inject_failure(session, stage, site_id)

        session.add(
            AppliedPackage(
                org_code=org,
                site_code=site_code,
                package_version=version,
                payload_digest=digest,
            )
        )
        session.commit()
        result.status = "applied"
        result.message = (
            f"应用成功：site_code={site_code} package_version={version}，"
            f"共写入 {result.total_written} 个对象"
        )
    except Exception as exc:  # noqa: BLE001 —— 任何异常都必须整体回滚
        session.rollback()
        result.status = "failed"
        result.rolled_back = True
        result.error = f"{type(exc).__name__}: {exc}"
        result.message = (
            f"应用失败并已整体回滚（无残留数据）：{type(exc).__name__}: "
            f"{str(exc).splitlines()[0][:200]}"
        )
    finally:
        session.close()
        result.duration_ms = int((time.monotonic() - started) * 1000)

    return result


__all__ = [
    "ApplyResult",
    "SimulationError",
    "package_digest",
    "apply_package",
    "MODEL_BY_STAGE",
]
