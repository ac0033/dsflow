"""演示项目端到端：原始数据 → 盘点 → 清洗 → 需求分布探索 → 按时间切分 → 月度特征 → 基线 → 线性模型（3 次探索 + 定稿）→ 预测 → 交付清单。

用法（在仓库根目录）：uv run python examples/demo_project/scripts/run_all.py

每一步是一个 notebook，由 `dsflow run` 启动平台自带的执行器逐格执行：命令、日志、退出码写进运行记录，
notebook 里的 SDK 写进同一条记录，输出写回 notebook 本身（步骤页的「讲解」就是围着它讲的）。
7.1 的三次探索用 --param 换特征、用 --save-to 另存到 outputs/，所以留在 notebook 里的是定稿那次。
跑完后模型登记为「候选」；验收、交付要由人在平台上确认（写明理由），脚本不替你决定。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = "steps/07_模型选择与训练/7.1_线性模型训练/nb_7.1.ipynb"
TRIAL = "steps/07_模型选择与训练/7.1_线性模型训练/outputs/nb_7.1_{}.ipynb"
PLAN = [
    ("1.1", "steps/01_数据预处理/1.1_数据源盘点/nb_1.1.ipynb", []),
    ("1.2", "steps/01_数据预处理/1.2_订单清洗/nb_1.2.ipynb", []),
    ("2.1", "steps/02_EDA/2.1_需求分布探索/nb_2.1.ipynb", []),
    ("3.1", "steps/03_数据划分/3.1_按时间切分/nb_3.1.ipynb", []),
    ("4.1", "steps/04_特征工程/4.1_月度特征/nb_4.1.ipynb", []),
    ("6.1", "steps/06_基线模型/6.1_基线模型/nb_6.1.ipynb", []),
    ("7.1", TRAIN, ["--param", "FEATURES=lag1", "--param", "FINAL=False", "--save-to", TRIAL.format("lag1")]),
    ("7.1", TRAIN, ["--param", "FEATURES=lag1,lag2,lag3", "--param", "FINAL=False", "--save-to", TRIAL.format("lag123")]),
    ("7.1", TRAIN, ["--param", "FEATURES=lag1,lag2,lag3,mean6", "--param", "FINAL=False", "--save-to", TRIAL.format("lag123_mean6")]),
    ("7.1", TRAIN, []),
    ("11.1", "steps/11_部署与交付/11.1_交付与预测/nb_11.1.ipynb", []),
]


def dsflow(*args: str, check: bool = True) -> int:
    return subprocess.run([sys.executable, "-m", "dsflow.cli", *args], check=check).returncode


def main() -> None:
    from dsflow.index.db import PlatformIndex

    if not (ROOT / "data" / "raw" / "orders.csv").is_file():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_data.py")], check=True)
    # 演示项目由自己的脚本写运行记录与交付清单，登记为可写
    PlatformIndex().add_project(ROOT, readonly=False)
    dsflow("data", "sync", str(ROOT))
    for step, notebook, extra in PLAN:
        print(f"\n===== {step} {' '.join(extra)} =====", flush=True)
        # 用 python -m + 相对路径启动（工作目录是项目根目录），运行记录里的复现命令换台机器也能用
        dsflow("run", step, "-p", str(ROOT), "--", "python", "-m", "dsflow.tracking.notebook", notebook, *extra)
    print("\n===== 交付清单 =====", flush=True)
    dsflow("delivery", "init", str(ROOT), "sku_demand_linear")
    print("\n===== 交接前核对 =====", flush=True)
    code = dsflow("check", str(ROOT), check=False)
    guide = dsflow("guide", "check", str(ROOT), check=False)
    print("\n完成。打开平台：uv run dsflow ui" + ("" if code == 0 and guide == 0 else "（核对有需要处理的问题，见上方）"))


if __name__ == "__main__":
    main()
