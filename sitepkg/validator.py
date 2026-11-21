"""S6-PLAN-006 配置包校验：JSON Schema + 跨文件引用 + 站点占用检查。

校验分三层：
  1. 结构层：用 jsonschema(Draft 2020-12) 对 8 个文件逐个校验；
  2. 引用层：权限模板编码 / SOP 模板编码+版本 / 预约规则编码 / 空间编码 / manifest 与 site 一致性；
  3. 数据层：site_code 在该 org 下是否已被占用（查一期 sites 表）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from .db import ENV_VAR

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
CATALOG_DIR = Path(__file__).resolve().parent.parent / "catalog"

#: 配置包文件清单（顺序即校验顺序）
FILES: dict[str, str] = {
    "manifest": "manifest.json",
    "site": "site.json",
    "spaces": "spaces.json",
    "role_bindings": "role_bindings.json",
    "sop_templates": "sop_templates.json",
    "kb_scopes": "kb_scopes.json",
    "price_book": "price_book.json",
    "miniapp_config": "miniapp_config.json",
}

#: 金额字段后缀（用于把 schema 的 type 错误归类为「金额非整数」）
AMOUNT_SUFFIX = "_fen"

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    code: str
    file: str
    path: str
    message: str
    severity: str = ERROR

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "file": self.file,
            "path": self.path,
            "message": self.message,
        }


@dataclass
class ValidationResult:
    package_dir: str
    site_code: str | None = None
    org_code: str | None = None
    package_version: str | None = None
    files_checked: int = 0
    object_counts: dict[str, int] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    db_checked: bool = False

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": "validate",
            "package": self.package_dir,
            "ok": self.ok,
            "site": {
                "org_code": self.org_code,
                "site_code": self.site_code,
                "package_version": self.package_version,
            },
            "summary": {
                "files_checked": self.files_checked,
                "object_total": sum(self.object_counts.values()),
                "object_counts": self.object_counts,
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "db_checked": self.db_checked,
            },
            "issues": [i.to_dict() for i in self.issues],
        }


class PackageLoadError(RuntimeError):
    """配置文件缺失或 JSON 无法解析。"""

    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__("；".join(f"{i.file}: {i.message}" for i in issues))


def _json_path(parts) -> str:
    out = "$"
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else f".{p}"
    return out


def load_schemas(schema_dir: Path = SCHEMA_DIR) -> dict[str, Draft202012Validator]:
    """加载并自检 8 个 JSON Schema，返回 validator 字典。"""
    validators: dict[str, Draft202012Validator] = {}
    for key, fname in FILES.items():
        raw = json.loads((schema_dir / fname).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(raw)
        validators[key] = Draft202012Validator(raw, format_checker=FormatChecker())
    return validators


def load_package(package_dir: str | Path) -> dict[str, Any]:
    """读取配置包为 {key: doc}，缺文件/坏 JSON 抛 PackageLoadError。"""
    pkg_dir = Path(package_dir)
    docs: dict[str, Any] = {}
    issues: list[Issue] = []
    for key, fname in FILES.items():
        path = pkg_dir / fname
        if not path.is_file():
            issues.append(Issue("FILE_MISSING", fname, "$", f"缺少必需文件：{fname}"))
            continue
        try:
            docs[key] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(
                Issue(
                    "JSON_PARSE_ERROR",
                    fname,
                    "$",
                    f"JSON 解析失败：{exc.msg}（第 {exc.lineno} 行第 {exc.colno} 列）",
                )
            )
    if issues:
        raise PackageLoadError(issues)
    return docs


def load_catalog(catalog_dir: str | Path = CATALOG_DIR) -> dict[str, Any]:
    """加载一期参考目录：权限模板、SOP 模板、预约规则。"""
    base = Path(catalog_dir)
    pt = json.loads((base / "permission_templates.json").read_text(encoding="utf-8"))
    sop = json.loads((base / "sop_templates.json").read_text(encoding="utf-8"))
    rr = json.loads((base / "reservation_rules.json").read_text(encoding="utf-8"))
    return {
        "permission_templates": {i["code"] for i in pt["permission_templates"]},
        "sop_versions": {i["code"]: set(i["versions"]) for i in sop["sop_templates"]},
        "reservation_rules": {i["code"] for i in rr["reservation_rules"]},
    }


def _is_amount_path(path_parts) -> bool:
    return bool(path_parts) and isinstance(path_parts[-1], str) and path_parts[-1].endswith(AMOUNT_SUFFIX)


class PackageValidator:
    """配置包校验器。engine 为空时跳过 site_code 占用检查（并给出 warning）。"""

    def __init__(
        self,
        catalog_dir: str | Path | None = None,
        engine: Engine | None = None,
        schema_dir: str | Path | None = None,
    ):
        self.validators = load_schemas(Path(schema_dir) if schema_dir else SCHEMA_DIR)
        self.catalog = load_catalog(catalog_dir or CATALOG_DIR)
        self.engine = engine

    # ---------- 结构层 ----------

    def _schema_issues(self, key: str, doc: Any) -> list[Issue]:
        fname = FILES[key]
        out: list[Issue] = []
        for err in sorted(self.validators[key].iter_errors(doc), key=lambda e: list(e.absolute_path)):
            parts = list(err.absolute_path)
            path = _json_path(parts)
            if err.validator == "type" and _is_amount_path(parts):
                out.append(
                    Issue(
                        "AMOUNT_NOT_INTEGER",
                        fname,
                        path,
                        f"金额必须是整数分，当前值为 {err.instance!r}（{err.message}）",
                    )
                )
            else:
                out.append(Issue("SCHEMA_INVALID", fname, path, err.message))
        return out

    # ---------- 引用层 ----------

    def _cross_file_issues(self, docs: dict[str, Any], schema_ok: set[str]) -> list[Issue]:
        out: list[Issue] = []
        cat = self.catalog

        if {"manifest", "site"} <= schema_ok:
            m, s = docs["manifest"], docs["site"]
            if m["site_code"] != s["site_code"]:
                out.append(
                    Issue(
                        "CODE_MISMATCH",
                        "site.json",
                        "$.site_code",
                        f"site.json 的 site_code={s['site_code']} 与 manifest.json 的 {m['site_code']} 不一致",
                    )
                )
            if m["org_code"] != s["org_code"]:
                out.append(
                    Issue(
                        "CODE_MISMATCH",
                        "site.json",
                        "$.org_code",
                        f"site.json 的 org_code={s['org_code']} 与 manifest.json 的 {m['org_code']} 不一致",
                    )
                )

        if "role_bindings" in schema_ok:
            seen: dict[tuple[str, str], int] = {}
            for idx, rb in enumerate(docs["role_bindings"]["role_bindings"]):
                code = rb["permission_template_code"]
                if code not in cat["permission_templates"]:
                    out.append(
                        Issue(
                            "REF_PERMISSION_TEMPLATE_MISSING",
                            "role_bindings.json",
                            f"$.role_bindings[{idx}].permission_template_code",
                            f"权限模板编码 {code} 在一期权限模板目录中不存在",
                        )
                    )
                sig = (rb["role_code"], code)
                if sig in seen:
                    out.append(
                        Issue(
                            "DUPLICATE_KEY",
                            "role_bindings.json",
                            f"$.role_bindings[{idx}]",
                            f"角色 {rb['role_code']} 与权限模板 {code} 的绑定重复（首次出现于 [{seen[sig]}]）",
                        )
                    )
                seen[sig] = idx

        if "sop_templates" in schema_ok:
            seen_sop: set[tuple[str, str]] = set()
            for idx, item in enumerate(docs["sop_templates"]["sop_templates"]):
                code, ver = item["template_code"], item["version"]
                if code not in cat["sop_versions"]:
                    out.append(
                        Issue(
                            "REF_SOP_TEMPLATE_MISSING",
                            "sop_templates.json",
                            f"$.sop_templates[{idx}].template_code",
                            f"SOP 模板编码 {code} 在一期 SOP 模板目录中不存在",
                        )
                    )
                elif ver not in cat["sop_versions"][code]:
                    available = ", ".join(sorted(cat["sop_versions"][code]))
                    out.append(
                        Issue(
                            "REF_SOP_VERSION_MISSING",
                            "sop_templates.json",
                            f"$.sop_templates[{idx}].version",
                            f"SOP 模板 {code} 不存在版本 {ver}（已发布版本：{available}）",
                        )
                    )
                if (code, ver) in seen_sop:
                    out.append(
                        Issue(
                            "DUPLICATE_KEY",
                            "sop_templates.json",
                            f"$.sop_templates[{idx}]",
                            f"SOP 模板 {code}@{ver} 重复声明",
                        )
                    )
                seen_sop.add((code, ver))

        if "spaces" in schema_ok:
            seen_space: set[str] = set()
            for idx, sp in enumerate(docs["spaces"]["spaces"]):
                rule = sp["reservation_rule_code"]
                if rule not in cat["reservation_rules"]:
                    out.append(
                        Issue(
                            "REF_RESERVATION_RULE_MISSING",
                            "spaces.json",
                            f"$.spaces[{idx}].reservation_rule_code",
                            f"预约规则编码 {rule} 在一期预约规则目录中不存在",
                        )
                    )
                code = sp["space_code"]
                if code in seen_space:
                    out.append(
                        Issue(
                            "DUPLICATE_KEY",
                            "spaces.json",
                            f"$.spaces[{idx}].space_code",
                            f"空间编码 {code} 在包内重复",
                        )
                    )
                seen_space.add(code)

        if {"kb_scopes", "spaces"} <= schema_ok:
            known_spaces = {sp["space_code"] for sp in docs["spaces"]["spaces"]}
            seen_kb: set[str] = set()
            for idx, kb in enumerate(docs["kb_scopes"]["kb_scopes"]):
                for j, sc in enumerate(kb["space_codes"]):
                    if sc not in known_spaces:
                        out.append(
                            Issue(
                                "REF_SPACE_MISSING",
                                "kb_scopes.json",
                                f"$.kb_scopes[{idx}].space_codes[{j}]",
                                f"知识库 {kb['kb_code']} 引用的空间编码 {sc} 不存在于 spaces.json",
                            )
                        )
                if kb["kb_code"] in seen_kb:
                    out.append(
                        Issue(
                            "DUPLICATE_KEY",
                            "kb_scopes.json",
                            f"$.kb_scopes[{idx}].kb_code",
                            f"知识库编码 {kb['kb_code']} 在包内重复",
                        )
                    )
                seen_kb.add(kb["kb_code"])

        if "price_book" in schema_ok:
            seen_item: set[str] = set()
            for idx, item in enumerate(docs["price_book"]["price_items"]):
                if item["item_code"] in seen_item:
                    out.append(
                        Issue(
                            "DUPLICATE_KEY",
                            "price_book.json",
                            f"$.price_items[{idx}].item_code",
                            f"价目项 {item['item_code']} 在包内重复",
                        )
                    )
                seen_item.add(item["item_code"])

        return out

    # ---------- 数据层 ----------

    def _db_issues(self, manifest: dict[str, Any]) -> list[Issue]:
        assert self.engine is not None
        org, site = manifest["org_code"], manifest["site_code"]
        version = manifest["package_version"]
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT id, package_version FROM sites "
                        "WHERE org_code = :org AND site_code = :site"
                    ),
                    {"org": org, "site": site},
                ).mappings().first()
                applied = False
                if row is not None:
                    applied = (
                        conn.execute(
                            text(
                                "SELECT 1 FROM applied_packages "
                                "WHERE org_code = :org AND site_code = :site "
                                "AND package_version = :ver"
                            ),
                            {"org": org, "site": site, "ver": version},
                        ).first()
                        is not None
                    )
        except SQLAlchemyError as exc:
            return [
                Issue(
                    "DB_CHECK_FAILED",
                    "manifest.json",
                    "$.site_code",
                    f"查询 sites 失败，未能确认 site_code 是否被占用：{type(exc).__name__}",
                    severity=WARNING,
                )
            ]
        if row is None:
            return []
        if applied:
            # 幂等键命中：该 site_code + package_version 已由本工具应用过，
            # 属于正常的重复 apply 场景，不按「占用冲突」处理。
            return [
                Issue(
                    "ALREADY_APPLIED",
                    "manifest.json",
                    "$.package_version",
                    f"已应用：site_code={site} package_version={version} "
                    f"已于此前写入（sites.id={row['id']}），本次不会产生重复数据",
                    severity=WARNING,
                )
            ]
        return [
            Issue(
                "SITE_CODE_OCCUPIED",
                "manifest.json",
                "$.site_code",
                f"site_code {site} 在组织 {org} 下已被占用"
                f"（sites.id={row['id']}，当前 package_version={row['package_version']}）",
            )
        ]

    # ---------- 对外入口 ----------

    def validate(self, package_dir: str | Path) -> ValidationResult:
        pkg_dir = Path(package_dir)
        result = ValidationResult(package_dir=str(pkg_dir))

        docs: dict[str, Any] = {}
        for key, fname in FILES.items():
            path = pkg_dir / fname
            if not path.is_file():
                result.issues.append(Issue("FILE_MISSING", fname, "$", f"缺少必需文件：{fname}"))
                continue
            try:
                docs[key] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                result.issues.append(
                    Issue(
                        "JSON_PARSE_ERROR",
                        fname,
                        "$",
                        f"JSON 解析失败：{exc.msg}（第 {exc.lineno} 行第 {exc.colno} 列）",
                    )
                )
        result.files_checked = len(docs)

        schema_ok: set[str] = set()
        for key, doc in docs.items():
            issues = self._schema_issues(key, doc)
            if not issues:
                schema_ok.add(key)
            result.issues.extend(issues)

        result.issues.extend(self._cross_file_issues(docs, schema_ok))

        if "manifest" in schema_ok:
            m = docs["manifest"]
            result.site_code = m["site_code"]
            result.org_code = m["org_code"]
            result.package_version = m["package_version"]

        result.object_counts = {
            "manifest": 1 if "manifest" in docs else 0,
            "site": 1 if "site" in docs else 0,
            "spaces": len(docs.get("spaces", {}).get("spaces", [])),
            "role_bindings": len(docs.get("role_bindings", {}).get("role_bindings", [])),
            "sop_templates": len(docs.get("sop_templates", {}).get("sop_templates", [])),
            "kb_scopes": len(docs.get("kb_scopes", {}).get("kb_scopes", [])),
            "price_book": len(docs.get("price_book", {}).get("price_items", [])),
            "miniapp_config": 1 if "miniapp_config" in docs else 0,
        }

        if self.engine is not None:
            if "manifest" in schema_ok:
                result.db_checked = True
                result.issues.extend(self._db_issues(docs["manifest"]))
        else:
            result.issues.append(
                Issue(
                    "DB_CHECK_SKIPPED",
                    "manifest.json",
                    "$.site_code",
                    f"未提供数据库连接（{ENV_VAR} 未设置），已跳过 site_code 占用检查",
                    severity=WARNING,
                )
            )

        result.issues.sort(key=lambda i: (i.file, i.path, i.code))
        return result


def validate_package(
    package_dir: str | Path,
    engine: Engine | None = None,
    catalog_dir: str | Path | None = None,
) -> ValidationResult:
    """便捷函数。"""
    return PackageValidator(catalog_dir=catalog_dir, engine=engine).validate(package_dir)


__all__ = [
    "FILES",
    "SCHEMA_DIR",
    "CATALOG_DIR",
    "Issue",
    "ValidationResult",
    "PackageValidator",
    "PackageLoadError",
    "load_package",
    "load_schemas",
    "load_catalog",
    "validate_package",
]
