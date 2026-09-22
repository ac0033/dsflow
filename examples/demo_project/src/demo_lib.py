"""演示项目的公共代码：各步产物位置、时间切分、SKU×月面板的历史特征、同类目季节系数、线性模型。

训练（7.1）和预测（11.1）用同一套特征定义，避免两边算法不一致。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STEPS = ROOT / "steps"
STEP_DIRS = {
    "1.1": "01_数据预处理/1.1_数据源盘点",
    "1.2": "01_数据预处理/1.2_订单清洗",
    "2.1": "02_EDA/2.1_需求分布探索",
    "3.1": "03_数据划分/3.1_按时间切分",
    "4.1": "04_特征工程/4.1_月度特征",
    "6.1": "06_基线模型/6.1_基线模型",
    "7.1": "07_模型选择与训练/7.1_线性模型训练",
    "11.1": "11_部署与交付/11.1_交付与预测",
}
FIRST_MONTH, LAST_MONTH = "2024-07", "2026-06"
SPLITS = {"训练": ("2024-07", "2025-12"), "验证": ("2026-01", "2026-03"), "最终评估": ("2026-04", "2026-06")}
FEATURES = {
    "lag1": "上月需求量",
    "lag2": "前 2 月需求量",
    "lag3": "前 3 月需求量",
    "mean6": "近 6 月均值",
    "season": "近 3 月均值 × 同类目季节系数",
}


def out(step: str) -> Path:
    d = STEPS / STEP_DIRS[step] / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def split_of(month: str) -> str:
    for name, (a, b) in SPLITS.items():
        if a <= month <= b:
            return name
    return "预测"


def add_history(panel: pd.DataFrame) -> pd.DataFrame:
    """每个 SKU 按月份排好，只用该月之前的需求量构造特征。"""
    panel = panel.sort_values(["SKU", "月份"]).reset_index(drop=True)
    g = panel.groupby("SKU")["需求量"]
    for k in (1, 2, 3):
        panel[f"lag{k}"] = g.shift(k)
    panel["mean3"] = panel[["lag1", "lag2", "lag3"]].mean(axis=1, skipna=False)
    panel["mean6"] = g.transform(lambda s: s.shift(1).rolling(6).mean())
    return panel


def season_table(panel: pd.DataFrame) -> dict[str, dict[str, float]]:
    """同类目季节系数 = 该类目某个自然月的平均月需求量 ÷ 该类目所有月份的平均月需求量。
    传进来的是哪些月份，就只用哪些月份估计（训练时只传训练期，避免用到未来）。"""
    by = panel.groupby(["类目", "月份"], as_index=False)["需求量"].sum()
    by["月"] = by["月份"].str[5:7].astype(int)
    table = {}
    for cat, d in by.groupby("类目"):
        overall = d["需求量"].mean()
        table[str(cat)] = {str(m): round(float(v / overall), 4) for m, v in d.groupby("月")["需求量"].mean().items()}
    return table


def add_season(panel: pd.DataFrame, table: dict[str, dict[str, float]]) -> pd.DataFrame:
    months = panel["月份"].str[5:7].astype(int).astype(str)
    coef = np.array([table[c][m] for c, m in zip(panel["类目"], months)], dtype=float)
    panel = panel.copy()
    panel["季节系数"] = coef
    panel["season"] = panel["mean3"] * coef
    return panel


def design(df: pd.DataFrame, features: list[str]) -> np.ndarray:
    return np.column_stack([np.ones(len(df)), *[df[f].to_numpy(dtype=float) for f in features]])


def fit(df: pd.DataFrame, features: list[str]) -> dict:
    """最小二乘线性回归；系数保留 6 位小数，保证同样的数据得到同样的模型文件。"""
    b, *_ = np.linalg.lstsq(design(df, features), df["需求量"].to_numpy(dtype=float), rcond=None)
    return {"type": "线性回归（最小二乘，预测值截到 0 以上）", "features": features,
            "intercept": round(float(b[0]), 6), "coef": {f: round(float(v), 6) for f, v in zip(features, b[1:])}}


def predict(model: dict, df: pd.DataFrame) -> np.ndarray:
    b = np.array([model["intercept"], *[model["coef"][f] for f in model["features"]]])
    return np.clip(design(df, model["features"]) @ b, 0, None)


def mae(y, p) -> float:
    return round(float(np.mean(np.abs(np.asarray(y, dtype=float) - np.asarray(p, dtype=float)))), 4)
