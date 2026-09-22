"""数据视图里被多处复用的组合操作。"""

from __future__ import annotations

from collections.abc import Callable

from . import profile as profiling
from .cache import DataCache, write_json


def ensure_profile(cache: DataCache, rel: str, progress: Callable = lambda f, m: None) -> dict:
    """读缓存的画像；没有就先准备（转换）再生成并缓存。"""
    cached = cache.cached_profile(rel)
    if cached:
        return cached
    parquet = cache.prepare(rel, progress)
    result = profiling.profile(parquet, progress)
    write_json(cache.profile_path(rel), result)
    return result
