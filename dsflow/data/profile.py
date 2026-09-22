"""数据状态画像：把一张大表压缩成人能读懂的逐列指标（L3 的"状态"）。

一次 SUMMARIZE 拿到范围、分位数、近似去重数；一次聚合拿到精确的非空数、负值 / 零值 / 空白串个数；
再按列取直方图（数值）、月度分布（时间）、取值排行（文本）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .browse import describe, row_count
from .engine import connect, ident, jsonable, scan, to_float

TOPK = 10
TOPK_MAX_DISTINCT = 200_000
BINS = 20
MAX_MONTHS = 120
PROFILE_VERSION = 2  # 结构有变化时加一，旧缓存自动重算

Progress = Callable[[float | None, str], None]


def bin_range(lo: float, hi: float, p01: float | None, p99: float | None) -> tuple[float, float]:
    """长尾明显时用 1%–99% 分位做分箱范围，两端极端值另计一格；否则用最小到最大。

    业务金额常见少数极大值：按最小—最大等宽分箱时几乎所有行都挤在第一格，图就没有信息量。
    """
    if p01 is None or p99 is None or p99 <= p01:
        return lo, hi
    core = p99 - p01
    if hi - p99 > 3 * core or p01 - lo > 3 * core:
        return p01, p99
    return lo, hi


def histogram(con, source: str, column: str, lo: float, hi: float, bins: int = BINS) -> dict:
    """[lo, hi] 内等宽分箱；under / over 是比 lo 小、比 hi 大的行数（未裁剪时都为 0）。"""
    q = f"CAST({ident(column)} AS DOUBLE)"
    under, over = con.execute(
        f"SELECT count(*) FILTER (WHERE {q} < ?), count(*) FILTER (WHERE {q} > ?) FROM {source}", [lo, hi]
    ).fetchone()
    if hi <= lo:
        n = con.execute(f"SELECT count(*) FROM {source} WHERE {q} = ?", [lo]).fetchone()[0]
        return {"edges": [lo, hi], "counts": [n], "under": under, "over": over}
    width = (hi - lo) / bins
    rows = con.execute(
        f"SELECT LEAST(CAST(FLOOR(({q} - ?) / ?) AS BIGINT), ?) AS b, count(*) FROM {source} "
        f"WHERE {q} IS NOT NULL AND isfinite({q}) AND {q} BETWEEN ? AND ? GROUP BY b ORDER BY b",
        [lo, width, bins - 1, lo, hi],
    ).fetchall()
    counts = [0] * bins
    for b, n in rows:
        counts[int(b)] += n
    return {"edges": [lo + i * width for i in range(bins)] + [hi], "counts": counts, "under": under, "over": over}


def tail_quantiles(con, source: str, columns: list[str]) -> dict[str, tuple[float | None, float | None]]:
    if not columns:
        return {}
    exprs = [f"approx_quantile(CAST({ident(c)} AS DOUBLE), [0.01, 0.99])" for c in columns]
    values = con.execute(f"SELECT {', '.join(exprs)} FROM {source}").fetchone()
    return {c: (to_float(v[0]), to_float(v[1])) if v else (None, None) for c, v in zip(columns, values)}


def periods(con, source: str, column: str) -> list[dict]:
    q = ident(column)
    rows = con.execute(
        f"SELECT strftime(date_trunc('month', {q}), '%Y-%m') AS p, count(*) FROM {source} "
        f"WHERE {q} IS NOT NULL GROUP BY p ORDER BY p"
    ).fetchall()
    if len(rows) > MAX_MONTHS:
        rows = con.execute(
            f"SELECT strftime({q}, '%Y') AS p, count(*) FROM {source} WHERE {q} IS NOT NULL GROUP BY p ORDER BY p"
        ).fetchall()
    return [{"label": p, "count": n} for p, n in rows]


def top_values(con, source: str, column: str, k: int = TOPK) -> list[dict]:
    q = ident(column)
    rows = con.execute(
        f"SELECT {q} AS v, count(*) AS n FROM {source} WHERE {q} IS NOT NULL GROUP BY v ORDER BY n DESC, v LIMIT {k}"
    ).fetchall()
    return [{"value": jsonable(v), "count": n} for v, n in rows]


def profile(parquet: Path, progress: Progress | None = None) -> dict:
    started = time.perf_counter()
    report = progress or (lambda _f, _m: None)
    con = connect()
    source = scan(parquet)
    columns = describe(parquet)
    rows = row_count(parquet)
    report(0.02, "汇总统计（SUMMARIZE）")
    summary = {r[0]: r for r in con.execute(f"SUMMARIZE SELECT * FROM {source}").fetchall()}

    aggs = []
    for c in columns:
        q = ident(c["name"])
        aggs.append(f"count({q})")
        if c["kind"] == "numeric":
            aggs += [f"count(*) FILTER (WHERE {q} < 0)", f"count(*) FILTER (WHERE {q} = 0)"]
        elif c["kind"] == "text":
            aggs.append(f"count(*) FILTER (WHERE trim(CAST({q} AS VARCHAR)) = '')")
    report(0.1, "精确计数（非空、负值、零值、空白）")
    values = iter(con.execute(f"SELECT {', '.join(aggs)} FROM {source}").fetchone())
    tails = tail_quantiles(con, source, [c["name"] for c in columns if c["kind"] == "numeric"])

    out = []
    for i, c in enumerate(columns):
        name, kind = c["name"], c["kind"]
        s = summary.get(name)
        non_null = next(values)
        col = {
            **c,
            "non_null": non_null,
            "null_count": rows - non_null,
            "null_rate": (rows - non_null) / rows if rows else 0.0,
            "distinct_approx": s[4] if s else None,
            "min": jsonable(s[2]) if s else None,
            "max": jsonable(s[3]) if s else None,
        }
        if kind == "numeric":
            col["negative"], col["zero"] = next(values), next(values)
            lo, hi = to_float(s[2]) if s else None, to_float(s[3]) if s else None
            col.update({
                "min": lo, "max": hi,
                "mean": to_float(s[5]), "std": to_float(s[6]),
                "q25": to_float(s[7]), "q50": to_float(s[8]), "q75": to_float(s[9]),
            })
            if lo is not None and hi is not None:
                col["p01"], col["p99"] = tails.get(name, (None, None))
                col["histogram"] = histogram(con, source, name, *bin_range(lo, hi, col["p01"], col["p99"]))
        elif kind == "temporal":
            col["periods"] = periods(con, source, name) if non_null else []
        if kind == "text":
            col["blank"] = next(values)
        if kind in ("text", "boolean", "other") and non_null:
            distinct = s[4] if s else None
            if distinct is not None and distinct <= TOPK_MAX_DISTINCT:
                col["top"] = top_values(con, source, name)
            else:
                col["top_skipped"] = f"不同值约 {distinct:,} 个，取值排行没有意义，已跳过"
        out.append(col)
        report(0.15 + 0.85 * (i + 1) / len(columns), f"逐列画像：{name}")

    return {
        "version": PROFILE_VERSION,
        "rows": rows,
        "column_count": len(columns),
        "columns": out,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seconds": round(time.perf_counter() - started, 2),
    }
