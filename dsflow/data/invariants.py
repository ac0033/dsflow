"""不变量检查：步骤声明"哪些东西必须不变"，平台在处理前后两份数据上自动核对。"""

from __future__ import annotations

from pathlib import Path

from ..core.schemas import InvariantCheck
from .browse import row_count
from .compare import _differs, _kinds, key_sql
from .engine import QueryError, connect, ident, scan, to_float

DESCRIPTIONS = {
    "row_count_equal": "行数不变",
    "row_count_max_change": "行数变化不超过容差",
    "sum_equal": "合计不变",
    "columns_unchanged": "按主键对齐后，这些列的原值不变",
    "no_new_nulls": "这些列不新增缺失",
    "keys_preserved": "处理前的主键在处理后都还在",
}


def _need(check: InvariantCheck, kinds_a: dict, kinds_b: dict, names: list[str], label: str) -> None:
    if not names:
        raise QueryError(f"「{DESCRIPTIONS[check.type]}」需要指定{label}")
    missing = [n for n in names if n not in kinds_a or n not in kinds_b]
    if missing:
        raise QueryError(f"两份数据都要有列：{'、'.join(missing)}")


def run_check(a: Path, b: Path, check: InvariantCheck) -> dict:
    con = connect()
    sa, sb = scan(a), scan(b)
    ka, kb = _kinds(con, sa), _kinds(con, sb)
    t = check.type
    out = {"type": t, "description": check.description or DESCRIPTIONS[t]}

    if t in ("row_count_equal", "row_count_max_change"):
        na, nb = row_count(a), row_count(b)
        limit = 0.0 if t == "row_count_equal" else check.tolerance
        change = abs(nb - na) / na if na else float(nb != 0)
        passed = nb == na if t == "row_count_equal" else change <= limit
        return {**out, "passed": passed, "detail": f"{na:,} → {nb:,} 行（变化 {nb - na:+,}）"}

    if t == "sum_equal":
        column = check.column or ""
        _need(check, ka, kb, [column], "合计列")
        q = ident(column)
        va = to_float(con.execute(f"SELECT sum({q}) FROM {sa}").fetchone()[0]) or 0.0
        vb = to_float(con.execute(f"SELECT sum({q}) FROM {sb}").fetchone()[0]) or 0.0
        passed = abs(vb - va) <= check.tolerance
        return {**out, "passed": passed, "detail": f"{column} 合计 {va:,.4f} → {vb:,.4f}（差 {vb - va:+,.4f}，容差 {check.tolerance:g}）"}

    if t == "no_new_nulls":
        _need(check, ka, kb, check.columns, "列")
        worse = []
        for c in check.columns:
            q = ident(c)
            na = con.execute(f"SELECT count(*) FILTER (WHERE {q} IS NULL) FROM {sa}").fetchone()[0]
            nb = con.execute(f"SELECT count(*) FILTER (WHERE {q} IS NULL) FROM {sb}").fetchone()[0]
            if nb > na:
                worse.append(f"{c} {na:,} → {nb:,}")
        return {**out, "passed": not worse, "detail": "缺失增加：" + "；".join(worse) if worse else "缺失数均未增加"}

    _need(check, ka, kb, check.key, "主键")
    klist, has_key, on = key_sql(check.key)
    ra, rb = f"(SELECT * FROM {sa} WHERE {has_key})", f"(SELECT * FROM {sb} WHERE {has_key})"
    null_a = con.execute(f"SELECT count(*) FILTER (WHERE NOT ({has_key})) FROM {sa}").fetchone()[0]
    null_note = f"；A 中 {null_a:,} 行主键为空，未参与核对" if null_a else ""

    if t == "keys_preserved":
        lost = con.execute(
            f"SELECT count(*) FROM (SELECT DISTINCT {klist} FROM {ra}) a ANTI JOIN (SELECT DISTINCT {klist} FROM {rb}) b ON {on}"
        ).fetchone()[0]
        return {**out, "passed": lost == 0, "detail": f"处理后找不到的主键 {lost:,} 个{null_note}"}

    if t == "columns_unchanged":
        _need(check, ka, kb, check.columns, "列")
        dup = con.execute(f"SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT {klist} FROM {rb})) FROM {rb}").fetchone()[0]
        if dup:
            return {**out, "passed": False, "detail": f"处理后主键重复 {dup:,} 行，无法逐行核对{null_note}"}
        conds = [_differs(ka[c], kb[c], f"a.{ident(c)}", f"b.{ident(c)}", check.tolerance or 1e-9)
                 for c in check.columns]
        counts = con.execute(
            f"SELECT {', '.join(f'count(*) FILTER (WHERE {x})' for x in conds)} FROM {ra} a JOIN {rb} b ON {on}"
        ).fetchone()
        changed = {c: n for c, n in zip(check.columns, counts) if n}
        detail = "；".join(f"{c} 有 {n:,} 行取值改变" for c, n in changed.items()) or "所有对齐行的原值一致"
        return {**out, "passed": not changed, "detail": detail + null_note}

    raise QueryError(f"不支持的检查：{t}")


def run_checks(a: Path, b: Path, checks: list[InvariantCheck]) -> list[dict]:
    results = []
    for check in checks:
        try:
            results.append(run_check(a, b, check))
        except QueryError as exc:
            results.append({"type": check.type, "description": check.description or DESCRIPTIONS.get(check.type, check.type),
                            "passed": False, "detail": f"无法检查：{exc}"})
    return results
