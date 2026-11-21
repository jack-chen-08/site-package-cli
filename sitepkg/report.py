"""人可读表格 + JSON 双输出渲染。"""

from __future__ import annotations

import json
import unicodedata
from typing import Any, Sequence

from .applier import ApplyResult
from .planner import PlanResult
from .validator import ValidationResult


def _width(text: str) -> int:
    """按东亚字符宽度计算显示列宽（中文占 2 列）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(text))


def _pad(text: str, width: int, align: str = "left") -> str:
    text = str(text)
    gap = max(0, width - _width(text))
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]], aligns: Sequence[str] | None = None) -> str:
    """渲染 ASCII 表格（无第三方依赖，中文对齐）。"""
    headers = [str(h) for h in headers]
    body = [[str(c) for c in row] for row in rows]
    ncols = len(headers)
    aligns = list(aligns or ["left"] * ncols)
    widths = []
    for i in range(ncols):
        widths.append(max([_width(headers[i])] + [_width(r[i]) for r in body]))

    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [sep, "| " + " | ".join(_pad(headers[i], widths[i]) for i in range(ncols)) + " |", sep]
    for row in body:
        out.append("| " + " | ".join(_pad(row[i], widths[i], aligns[i]) for i in range(ncols)) + " |")
    out.append(sep)
    return "\n".join(out)


def render_validate(result: ValidationResult) -> str:
    lines = [
        f"配置包目录 : {result.package_dir}",
        f"目标站点   : {result.org_code or '-'} / {result.site_code or '-'}    "
        f"package_version={result.package_version or '-'}",
        f"文件 / 对象: {result.files_checked} 个文件 / {sum(result.object_counts.values())} 个对象",
        f"数据库检查 : {'已执行（site_code 占用）' if result.db_checked else '已跳过'}",
        "",
    ]
    if result.issues:
        rows = [
            [i.code, i.severity, i.file, i.path, i.message]
            for i in result.issues
        ]
        lines.append(table(["错误码", "级别", "文件", "路径", "说明"], rows))
    else:
        lines.append("（无问题）")
    lines.append("")
    lines.append(
        f"结论: {'通过' if result.ok else '未通过'}"
        f"（error={len(result.errors)}, warning={len(result.warnings)}）"
    )
    return "\n".join(lines)


def render_plan(plan: PlanResult) -> str:
    lines = [
        f"配置包目录 : {plan.package_dir}",
        f"目标站点   : {plan.org_code} / {plan.site_code}    package_version={plan.package_version}",
        f"站点是否已由配置包管理 : {'是' if plan.managed else '否'}    "
        f"该版本是否已应用 : {'是' if plan.applied else '否'}",
        "",
    ]
    if plan.items:
        lines.append(table(["阶段", "对象键", "动作", "说明"], plan.rows()))
    else:
        lines.append("（无可比对对象）")
    lines.append("")
    lines.append(
        f"汇总: 新增 {plan.counts['create']} / 跳过 {plan.counts['skip']} / "
        f"冲突 {plan.counts['conflict']}（合计 {len(plan.items)}）"
    )
    if plan.has_conflict:
        lines.append("提示: 存在冲突项，plan 未做任何写入；如需升级请人工确认差异字段。")
    return "\n".join(lines)


def render_apply(result: ApplyResult) -> str:
    lines = [
        f"目标站点   : {result.org_code} / {result.site_code}    "
        f"package_version={result.package_version}",
        f"状态       : {result.status}",
        f"消息       : {result.message}",
        f"内容摘要   : {result.payload_digest[:16]}…    耗时 {result.duration_ms} ms",
        "",
    ]
    if result.counts:
        lines.append(table(["阶段", "新增", "更新", "跳过"], result.rows(), ["left", "right", "right", "right"]))
    if result.error:
        lines.append("")
        lines.append(f"错误详情   : {result.error}")
    return "\n".join(lines)


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def emit(human: str, payload: dict[str, Any], json_only: bool = False) -> None:
    """同时输出人可读表格与 JSON；--json 只输出 JSON（便于管道消费）。"""
    if json_only:
        print(dumps(payload))
        return
    print(human)
    print("")
    print("--- JSON ---")
    print(dumps(payload))


__all__ = ["table", "render_validate", "render_plan", "render_apply", "dumps", "emit"]
