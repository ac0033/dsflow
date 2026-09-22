"""答疑能用的工具：协议登记表里只读的那几个，一个也不多给。

答疑是"看懂已经做过的事"，不是"接着做事"：写文件、跑 notebook、改状态、记审批这些都不在名单里，
名单以外的调用在 `session` 里直接回绝，模型再怎么要求也改不了项目。
"""

from __future__ import annotations

# 顺序就是给模型看的顺序：先定位，再读原文，再看数据，最后看运行记录。
READONLY = (
    "steps_list",      # 项目有哪些步骤、各在什么状态
    "step_get",        # 一步的轮次、文件、说明卡
    "file_read",       # 读项目里的文本文件（notebook、计划、报告）
    "data_peek",       # 看数据表前几行与全部列名
    "data_query",      # 对一份数据文件跑一条只读 SQL（数一数、分组汇总）
    "data_list",       # 数据集演变链
    "guide_get",       # 某一步的讲解原文与核对结果
    "vocabulary_get",  # 项目术语表
    "runs_list",       # 最近的运行记录
    "run_get",         # 一次运行的指标与日志尾部
)


def specs() -> list[dict]:
    """名单里的工具 → 通用工具定义 {name, description, parameters}。"""
    from ..protocol import REGISTRY

    return [{"name": name, "description": REGISTRY[name].description, "parameters": REGISTRY[name].schema()}
            for name in READONLY if name in REGISTRY]


def allowed(name: str) -> bool:
    return name in READONLY
