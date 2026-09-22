"""版本对比（Delta）：两份数据之间改了什么、改在哪里。

- compare_profiles：结构差异、行数差、逐列统计差（基于两份画像，不重新扫描）。
- distribution：同一列在两边的分布，数值列用同一组分箱。
- segment_impact：按分组列统计两边行数，找出"变化集中在哪里"。
- key_diff：按主键对齐，统计只在一边的行、共同行里逐列变了多少，并给样例。
"""

from __future__ import annotations

from pathlib import Path

from .engine import QueryError, connect, ident, jsonable, kind_of, scan, to_float
from .profile import BINS

SEGMENT_TOP = 30
NULL_LABEL = "（空）"


def _pct(a: float, b: float) -> float | None:
    return (b - a) / a if a else None


def compare_profiles(pa: dict, pb: dict) -> dict:
    cols_a = {c["name"]: c for c in pa["columns"]}
    cols_b = {c["name"]: c for c in pb["columns"]}
    added = [n for n in cols_b if n not in cols_a]
    removed = [n for n in cols_a if n not in cols_b]
    type_changed = [
        {"name": n, "a": cols_a[n]["type"], "b": cols_b[n]["type"]}
        for n in cols_a if n in cols_b and cols_a[n]["type"] != cols_b[n]["type"]
    ]
    columns = []
    for name in (n for n in cols_a if n in cols_b):
        a, b = cols_a[name], cols_b[name]
        row = {
            "name": name, "kind": b["kind"],
            "null_a": a["null_count"], "null_b": b["null_count"],
            "null_rate_a": a["null_rate"], "null_rate_b": b["null_rate"],
            "distinct_a": a.get("distinct_approx"), "distinct_b": b.get("distinct_approx"),
        }
        flags = []
        if a["null_count"] != b["null_count"]:
            flags.append("缺失数变化")
        if a["kind"] == "numeric" and b["kind"] == "numeric":
            row.update(mean_a=a.get("mean"), mean_b=b.get("mean"), q50_a=a.get("q50"), q50_b=b.get("q50"),
                       min_a=a.get("min"), min_b=b.get("min"), max_a=a.get("max"), max_b=b.get("max"))
            ma, mb = a.get("mean"), b.get("mean")
            if ma is not None and mb is not None and abs(mb - ma) > 1e-9 * max(1.0, abs(ma)):
                flags.append("均值变化")
            if (a.get("min"), a.get("max")) != (b.get("min"), b.get("max")):
                flags.append("范围变化")
        da, db = a.get("distinct_approx"), b.get("distinct_approx")
        if da and db and abs(db - da) / da > 0.02:
            flags.append("不同值个数变化")
        row["flags"] = flags
        row["score"] = abs(b["null_rate"] - a["null_rate"]) + (
            abs(_pct(ma, mb) or 0) if "均值变化" in flags else 0) + 0.001 * len(flags)
        columns.append(row)
    columns.sort(key=lambda r: -r["score"])

    rows_a, rows_b = pa["rows"], pb["rows"]
    return {
        "rows": {"a": rows_a, "b": rows_b, "delta": rows_b - rows_a, "pct": _pct(rows_a, rows_b)},
        "column_count": {"a": pa["column_count"], "b": pb["column_count"]},
        "schema": {"added": added, "removed": removed, "type_changed": type_changed},
        "columns": columns,
        "changed_columns": sum(1 for c in columns if c["flags"]),
    }


def _kinds(con, source: str) -> dict[str, str]:
    return {r[0]: kind_of(r[1]) for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()}


def distribution(a: Path, b: Path, column: str, bins: int = BINS) -> dict:
    con = connect()
    sa, sb = scan(a), scan(b)
    ka, kb = _kinds(con, sa), _kinds(con, sb)
    if column not in ka or column not in kb:
        raise QueryError(f"两份数据都要有列「{column}」")
    q = ident(column)
    if ka[column] == kb[column] == "numeric":
        from .profile import bin_range, histogram, tail_quantiles

        lo, hi = (to_float(v) for v in con.execute(
            f"SELECT least((SELECT min({q}) FROM {sa}), (SELECT min({q}) FROM {sb})), "
            f"greatest((SELECT max({q}) FROM {sa}), (SELECT max({q}) FROM {sb}))").fetchone())
        if lo is None:
            return {"kind": "numeric", "edges": [], "a": [], "b": [], "under": [0, 0], "over": [0, 0]}
        (a01, a99), (b01, b99) = tail_quantiles(con, sa, [column])[column], tail_quantiles(con, sb, [column])[column]
        p01 = min(x for x in (a01, b01) if x is not None) if a01 is not None or b01 is not None else None
        p99 = max(x for x in (a99, b99) if x is not None) if a99 is not None or b99 is not None else None
        lo, hi = bin_range(lo, hi, p01, p99)
        ha, hb = histogram(con, sa, column, lo, hi, bins), histogram(con, sb, column, lo, hi, bins)
        return {"kind": "numeric", "edges": ha["edges"], "a": ha["counts"], "b": hb["counts"],
                "under": [ha["under"], hb["under"]], "over": [ha["over"], hb["over"]]}
    if ka[column] == kb[column] == "temporal":
        from .profile import periods
        pa, pb = {p["label"]: p["count"] for p in periods(con, sa, column)}, \
            {p["label"]: p["count"] for p in periods(con, sb, column)}
        labels = sorted(set(pa) | set(pb))
        return {"kind": "temporal", "labels": labels, "a": [pa.get(x, 0) for x in labels],
                "b": [pb.get(x, 0) for x in labels]}
    counts = _segment_counts(con, sa, sb, column)
    counts.sort(key=lambda r: -(r[1] + r[2]))
    head, tail = counts[:12], counts[12:]
    labels = [r[0] for r in head] + (["其他"] if tail else [])
    return {"kind": "categorical", "labels": labels,
            "a": [r[1] for r in head] + ([sum(r[1] for r in tail)] if tail else []),
            "b": [r[2] for r in head] + ([sum(r[2] for r in tail)] if tail else [])}


def _segment_counts(con, sa: str, sb: str, column: str) -> list[tuple[str, int, int]]:
    q = ident(column)
    rows = con.execute(
        f"WITH a AS (SELECT CAST({q} AS VARCHAR) AS v, count(*) AS n FROM {sa} GROUP BY 1), "
        f"b AS (SELECT CAST({q} AS VARCHAR) AS v, count(*) AS n FROM {sb} GROUP BY 1) "
        f"SELECT coalesce(a.v, b.v), coalesce(a.n, 0), coalesce(b.n, 0) "
        f"FROM a FULL OUTER JOIN b ON a.v IS NOT DISTINCT FROM b.v"
    ).fetchall()
    return [(NULL_LABEL if v is None else v, int(na), int(nb)) for v, na, nb in rows]


def segment_impact(a: Path, b: Path, column: str, top: int = SEGMENT_TOP) -> dict:
    con = connect()
    sa, sb = scan(a), scan(b)
    if column not in _kinds(con, sa) or column not in _kinds(con, sb):
        raise QueryError(f"两份数据都要有分组列「{column}」")
    counts = _segment_counts(con, sa, sb, column)
    total_a = sum(r[1] for r in counts)
    total_b = sum(r[2] for r in counts)
    total_delta = total_b - total_a
    removed = sum(max(0, na - nb) for _, na, nb in counts)
    added = sum(max(0, nb - na) for _, na, nb in counts)
    rows = []
    for value, na, nb in counts:
        delta = nb - na
        rows.append({
            "value": value, "a": na, "b": nb, "delta": delta, "pct": _pct(na, nb),
            "share_a": na / total_a if total_a else None,
            # 本组占全部减少（或增加）行数的比例：与 share_a 相比明显偏大，说明变化集中在这一组
            "share_of_change": (-delta / removed if delta < 0 and removed else
                                delta / added if delta > 0 and added else 0.0),
        })
    rows.sort(key=lambda r: (-abs(r["delta"]), r["value"]))
    concentrated = [
        r for r in rows
        if r["delta"] and r["share_a"] is not None and r["share_of_change"] >= 0.2
        and r["share_of_change"] >= 2 * r["share_a"]
    ]
    return {
        "column": column, "groups": len(rows), "total_a": total_a, "total_b": total_b,
        "delta": total_delta, "removed": removed, "added": added,
        "rows": rows[:top], "other_groups": max(0, len(rows) - top),
        "concentrated": [r["value"] for r in concentrated[:5]],
    }


def _differs(ka: str, kb: str, qa: str, qb: str, tolerance: float = 1e-9) -> str:
    if ka != kb:
        return f"CAST({qa} AS VARCHAR) IS DISTINCT FROM CAST({qb} AS VARCHAR)"
    if ka == "numeric":
        return (f"(({qa} IS NULL) <> ({qb} IS NULL) OR abs(CAST({qa} AS DOUBLE) - CAST({qb} AS DOUBLE)) > "
                f"{tolerance} * greatest(1.0, abs(CAST({qa} AS DOUBLE))))")
    return f"{qa} IS DISTINCT FROM {qb}"


def key_sql(keys: list[str]) -> tuple[str, str, str]:
    """(主键列清单, "主键都不为空"条件, a/b 两边按主键相等的连接条件)。"""
    return (
        ", ".join(ident(k) for k in keys),
        " AND ".join(f"{ident(k)} IS NOT NULL" for k in keys),
        " AND ".join(f"a.{ident(k)} = b.{ident(k)}" for k in keys),
    )


def key_diff(a: Path, b: Path, keys: list[str], sample: int = 5) -> dict:
    if not keys:
        raise QueryError("至少指定一个主键列")
    con = connect()
    sa, sb = scan(a), scan(b)
    ka, kb = _kinds(con, sa), _kinds(con, sb)
    missing = [k for k in keys if k not in ka or k not in kb]
    if missing:
        raise QueryError(f"两份数据都要有主键列：{'、'.join(missing)}")
    klist, has_key, on = key_sql(keys)
    # 主键为空的行无法对齐：单独计数，不参与对齐（否则"空 = 空"会互相配对、把行数放大）
    ra, rb = f"(SELECT * FROM {sa} WHERE {has_key})", f"(SELECT * FROM {sb} WHERE {has_key})"
    da, db = f"(SELECT DISTINCT {klist} FROM {ra})", f"(SELECT DISTINCT {klist} FROM {rb})"

    def key_stats(source: str, distinct: str) -> tuple[int, int]:
        total, null_keys = con.execute(
            f"SELECT count(*), count(*) FILTER (WHERE NOT ({has_key})) FROM {source}").fetchone()
        return null_keys, total - null_keys - con.execute(f"SELECT count(*) FROM {distinct}").fetchone()[0]

    null_a, dup_a = key_stats(sa, da)
    null_b, dup_b = key_stats(sb, db)
    result = {
        "keys": keys, "null_keys_a": null_a, "null_keys_b": null_b, "duplicates_a": dup_a, "duplicates_b": dup_b,
        "only_a": con.execute(f"SELECT count(*) FROM {da} a ANTI JOIN {db} b ON {on}").fetchone()[0],
        "only_b": con.execute(f"SELECT count(*) FROM {db} a ANTI JOIN {da} b ON {on}").fetchone()[0],
        "matched": con.execute(f"SELECT count(*) FROM {da} a SEMI JOIN {db} b ON {on}").fetchone()[0],
    }

    def rows_only(left: str, right: str) -> list[dict]:
        cols, rows = _run(con, f"SELECT a.* FROM {left} a ANTI JOIN {right} b ON {on} LIMIT {sample}")
        return [dict(zip(cols, (jsonable(v) for v in r))) for r in rows]

    result["sample_only_a"] = rows_only(ra, rb)
    result["sample_only_b"] = rows_only(rb, ra)
    sa, sb = ra, rb

    common = [c for c in ka if c in kb and c not in keys]
    if result["duplicates_a"] or result["duplicates_b"]:
        result["changed_skipped"] = "主键有重复，按主键逐列比对会把行数放大，已跳过逐列变化统计"
        return result
    if not common:
        result.update(changed_rows=0, changed_by_column={}, sample_changed=[])
        return result
    conds = {c: _differs(ka[c], kb[c], f"a.{ident(c)}", f"b.{ident(c)}") for c in common}
    any_changed = " OR ".join(f"({x})" for x in conds.values())
    aggs = [f"count(*) FILTER (WHERE {any_changed})"] + [f"count(*) FILTER (WHERE {x})" for x in conds.values()]
    counts = con.execute(f"SELECT {', '.join(aggs)} FROM {sa} a JOIN {sb} b ON {on}").fetchone()
    result["changed_rows"] = counts[0]
    result["changed_by_column"] = {c: n for c, n in zip(common, counts[1:]) if n}

    changed_cols = list(result["changed_by_column"])
    samples = []
    if changed_cols:
        select = ", ".join([f"a.{ident(k)}" for k in keys] + [f"a.{ident(c)}, b.{ident(c)}" for c in changed_cols])
        where = " OR ".join(f"({conds[c]})" for c in changed_cols)
        _, rows = _run(con, f"SELECT {select} FROM {sa} a JOIN {sb} b ON {on} WHERE {where} LIMIT {sample}")
        for r in rows:
            key_vals = {k: jsonable(v) for k, v in zip(keys, r[: len(keys)])}
            diffs = []
            for i, c in enumerate(changed_cols):
                va, vb = r[len(keys) + 2 * i], r[len(keys) + 2 * i + 1]
                if con.execute(f"SELECT {_differs(ka[c], kb[c], '$1', '$2')}", [va, vb]).fetchone()[0]:
                    diffs.append({"column": c, "a": jsonable(va), "b": jsonable(vb)})
            samples.append({"key": key_vals, "changes": diffs})
    result["sample_changed"] = samples
    return result


def _run(con, sql: str) -> tuple[list[str], list[tuple]]:
    cur = con.execute(sql)
    return [d[0] for d in cur.description], cur.fetchall()
