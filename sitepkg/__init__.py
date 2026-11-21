"""会员空间平台 —— 配置包 CLI（S6-PLAN-006）。

模块：
  validator.py  结构 / 引用 / 占用三层校验
  planner.py    只读比对，输出新增-跳过-冲突
  applier.py    单事务按依赖顺序写入，幂等 + 整体回滚
  db.py         连接串、只读事务、DDL 工具
  models.py     一期最小表 ORM
  report.py     表格 + JSON 双输出
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
