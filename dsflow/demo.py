"""`dsflow demo`：三分钟看到整条链——agent 交计划 → 网页审批 → agent 继续。

建一个演示项目（一份三行的采购单、一个已经写好计划、等你审批的步骤 1.1），登记进平台，
然后告诉你打开哪个网址、在另一个终端跑哪条命令。不需要任何 LLM。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .attach import attach
from .core.project import ProjectError, project_id_for
from .paths import templates_dir

ORDERS_CSV = "订单号,商品名称,数量,金额\nSO0001,A100 螺栓,2,36.0\nSO0002,B200 垫片,10,15.5\nSO0003,A100 螺栓,1,18.0\n"
PLAN_MD = """# 1.1 计划：确认采购单能不能直接用

**目的**：确认 data/raw/orders.csv 这份采购单每一行代表什么、有没有空值，判断后面的统计能不能直接算。

**输入**：data/raw/orders.csv（一行 = 一个采购行）。

**处理办法**：读入全部行，统计行数与空值个数，写进 outputs/summary.json。

**产物**：outputs/summary.json；用户报告 report.md；讲解 guide.yaml。

**验收标准**：行数与文件一致，空值个数为 0。

**停止条件**：出现空值或重复的订单号就停下来，先向用户说明。
"""
STEP = {"id": "1.1", "stage": 1, "order": 1, "title": "确认采购单", "status": "pending_approval",
        "op": "确认采购单能不能直接用", "finding": "", "decision": ""}


def make_demo(target: str | Path, python: str | Path | None = None) -> dict:
    root = Path(target).resolve()
    if root.exists() and any(root.iterdir()):
        raise ProjectError(f"{root} 已经有东西了；换一个空目录")
    shutil.copytree(templates_dir() / "project", root, dirs_exist_ok=True)
    for rel in ("dsflow.yaml", "lifecycle/steps.json"):
        f = root / rel
        f.write_text(f.read_text(encoding="utf-8").replace("__NAME__", "DSFlow 演示"), encoding="utf-8")
    reg = json.loads((root / "lifecycle/steps.json").read_text(encoding="utf-8"))
    stage = reg["stages"][0]
    step = {**STEP, "dir": f"{stage['dir']}/1.1_确认采购单"}
    reg["steps"] = [step]
    (root / "lifecycle/steps.json").write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raw = root / "data" / "raw" / "orders.csv"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(ORDERS_CSV, encoding="utf-8")
    plan = root / step["dir"] / "plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(PLAN_MD, encoding="utf-8")
    lines = attach(root, python=python, force=True)
    return {"root": root, "id": project_id_for(root), "step": "1.1", "attach": lines}
