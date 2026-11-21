#!/usr/bin/env python3
"""会员空间平台 —— site_package 配置包命令行工具（S6-PLAN-006）。

用法：
    site_package.py validate <包目录> [--json] [--no-db]
    site_package.py plan     <包目录> [--json]
    site_package.py apply    <包目录> [--json] [--fail-at 阶段]

数据库连接串从环境变量 SITE_PACKAGE_DATABASE_URL 读取，命令行不接受口令参数。

退出码：
    validate  0=通过  1=存在问题
    plan      0=无冲突 1=校验未通过 2=存在冲突 3=执行错误
    apply     0=已应用/已应用过 1=校验未通过 2=冲突 3=执行失败（已回滚） 4=配置错误
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from sqlalchemy.exc import SQLAlchemyError

from sitepkg import __version__
from sitepkg.applier import apply_package
from sitepkg.db import ConfigError, make_engine
from sitepkg.planner import STAGE_ORDER, plan_package
from sitepkg.report import emit, render_apply, render_plan, render_validate
from sitepkg.validator import PackageLoadError, PackageValidator, load_package

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_CONFLICT = 2
EXIT_FAILED = 3
EXIT_CONFIG = 4

PACKAGE_ARG = click.argument(
    "package_dir", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
CATALOG_OPT = click.option(
    "--catalog",
    "catalog_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="一期参考目录（默认仓库内 catalog/）",
)
JSON_OPT = click.option("--json", "as_json", is_flag=True, help="只输出 JSON（不打印表格）")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="site_package")
def cli() -> None:
    """会员空间平台配置包工具：validate / plan / apply。"""


def _try_engine(required: bool):
    try:
        return make_engine()
    except ConfigError as exc:
        if required:
            click.echo(f"[配置错误] {exc}", err=True)
            sys.exit(EXIT_CONFIG)
        click.echo(f"[提示] {exc}；本次以离线模式运行，跳过 site_code 占用检查。", err=True)
        return None


def _validate_or_exit(package_dir: Path, as_json: bool, catalog_dir, engine):
    """plan / apply 前置校验：不通过直接以 EXIT_INVALID 结束。"""
    check = PackageValidator(catalog_dir=catalog_dir, engine=engine).validate(package_dir)
    if not check.ok:
        emit(render_validate(check), check.to_dict(), as_json)
        click.echo(f"校验未通过（{len(check.errors)} 个错误），已中止。", err=True)
        sys.exit(EXIT_INVALID)
    return check


@cli.command("validate")
@PACKAGE_ARG
@JSON_OPT
@CATALOG_OPT
@click.option("--no-db", is_flag=True, help="离线校验：跳过 site_code 占用检查")
def validate_cmd(package_dir: Path, as_json: bool, catalog_dir, no_db: bool) -> None:
    """按 S6-PLAN-006 校验配置包（结构 + 跨文件引用 + site_code 占用）。"""
    engine = None if no_db else _try_engine(required=False)
    result = PackageValidator(catalog_dir=catalog_dir, engine=engine).validate(package_dir)
    emit(render_validate(result), result.to_dict(), as_json)
    sys.exit(EXIT_OK if result.ok else EXIT_INVALID)


@cli.command("plan")
@PACKAGE_ARG
@JSON_OPT
@CATALOG_OPT
def plan_cmd(package_dir: Path, as_json: bool, catalog_dir) -> None:
    """dry-run：只读比对目标环境，输出新增 / 跳过 / 冲突清单，不写入任何数据。"""
    engine = _try_engine(required=True)
    _validate_or_exit(package_dir, as_json, catalog_dir, engine)
    pkg = load_package(package_dir)
    try:
        result = plan_package(pkg, engine, str(package_dir))
    except SQLAlchemyError as exc:
        click.echo(f"[数据库错误] {type(exc).__name__}: {exc}", err=True)
        sys.exit(EXIT_FAILED)
    emit(render_plan(result), result.to_dict(), as_json)
    sys.exit(EXIT_CONFLICT if result.has_conflict else EXIT_OK)


@cli.command("apply")
@PACKAGE_ARG
@JSON_OPT
@CATALOG_OPT
@click.option(
    "--fail-at",
    type=click.Choice(list(STAGE_ORDER)),
    default=None,
    help="故障演练：在指定阶段注入失败，用于验证「中途失败整体回滚」",
)
def apply_cmd(package_dir: Path, as_json: bool, catalog_dir, fail_at: str | None) -> None:
    """在单个事务内按依赖顺序写入配置包，失败整体回滚，按 site_code+package_version 幂等。"""
    engine = _try_engine(required=True)
    _validate_or_exit(package_dir, as_json, catalog_dir, engine)
    try:
        pkg = load_package(package_dir)
    except PackageLoadError as exc:
        for issue in exc.issues:
            click.echo(f"[{issue.code}] {issue.file} {issue.path}: {issue.message}", err=True)
        sys.exit(EXIT_INVALID)

    result = apply_package(pkg, engine, fail_at=fail_at, package_dir=str(package_dir))
    emit(render_apply(result), result.to_dict(), as_json)

    if result.status == "conflict":
        sys.exit(EXIT_CONFLICT)
    if result.status == "failed":
        sys.exit(EXIT_FAILED)
    sys.exit(EXIT_OK)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
