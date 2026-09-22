"""分页浏览、随机抽样、只读 SQL。每次只取可视区的行，排序与筛选在 DuckDB 里完成。"""

from __future__ import annotations

import re
from pathlib import Path

import pyarrow.parquet as pq

from .engine import QueryError, connect, fetch, ident, jsonable, kind_of, lit, sandbox, scan

PAGE_MAX = 1000
SQL_ROW_MAX = 1000
SQL_TIMEOUT = 20.0
FILTER_OPS = {"eq": "=", "ne": "!=", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}
_STRINGS = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")
_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_QUERY_START = re.compile(r"^\s*(select|with|from)\b", re.I)


def describe(parquet: Path) -> list[dict]:
    rows = connect().execute(f"DESCRIBE SELECT * FROM {scan(parquet)}").fetchall()
    return [{"name": r[0], "type": r[1], "kind": kind_of(r[1])} for r in rows]


def row_count(parquet: Path) -> int:
    return pq.ParquetFile(parquet).metadata.num_rows


def build_where(filters: list[dict] | None, names: set[str]) -> tuple[str, list]:
    clauses, params = [], []
    for f in filters or []:
        column, op = f.get("column"), f.get("op")
        if column not in names:
            raise QueryError(f"筛选列不存在：{column}")
        q = ident(column)
        if op in FILTER_OPS:
            clauses.append(f"{q} {FILTER_OPS[op]} ?")
            params.append(f.get("value"))
        elif op == "contains":
            clauses.append(f"CAST({q} AS VARCHAR) ILIKE ?")
            params.append(f"%{f.get('value', '')}%")
        elif op == "is_null":
            clauses.append(f"{q} IS NULL")
        elif op == "not_null":
            clauses.append(f"{q} IS NOT NULL")
        else:
            raise QueryError(f"不支持的筛选方式：{op}")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _source(parquet: Path, names: set[str]) -> tuple[str, str]:
    """返回 (FROM 子句, 原始行号表达式)。行号 = 文件中的第几行（从 0 起），用于回溯原记录。"""
    if "file_row_number" in names:
        return scan(parquet), "NULL"
    return f"read_parquet({lit(parquet)}, file_row_number=true)", "file_row_number"


def page(parquet: Path, offset: int = 0, limit: int = 200, sort: str | None = None, desc: bool = False,
         filters: list[dict] | None = None) -> dict:
    columns = describe(parquet)
    names = {c["name"] for c in columns}
    limit = max(1, min(limit, PAGE_MAX))
    offset = max(0, offset)
    source, rownum = _source(parquet, names)
    where, params = build_where(filters, names)
    order = ""
    if sort:
        if sort not in names:
            raise QueryError(f"排序列不存在：{sort}")
        order = f" ORDER BY {ident(sort)} {'DESC' if desc else 'ASC'} NULLS LAST"
        if rownum != "NULL":
            order += f", {rownum}"
    select = ", ".join(ident(c["name"]) for c in columns)
    con = connect()
    _, rows = fetch(con, f"SELECT {rownum} AS __row, {select} FROM {source}{where}{order} LIMIT ? OFFSET ?",
                    params + [limit, offset])
    total = fetch(con, f"SELECT count(*) FROM {source}{where}", params)[1][0][0] if where else row_count(parquet)
    return {
        "columns": columns,
        "rows": [[jsonable(v) for v in r] for r in rows],
        "offset": offset,
        "total": total,
    }


def sample(parquet: Path, n: int = 200, seed: int = 42) -> dict:
    columns = describe(parquet)
    names = {c["name"] for c in columns}
    n = max(1, min(n, PAGE_MAX))
    source, rownum = _source(parquet, names)
    select = ", ".join(ident(c["name"]) for c in columns)
    _, rows = fetch(connect(), f"SELECT {rownum} AS __row, {select} FROM {source} "
                               f"USING SAMPLE reservoir({int(n)} ROWS) REPEATABLE ({int(seed)}) ORDER BY 1")
    return {"columns": columns, "rows": [[jsonable(v) for v in r] for r in rows], "offset": 0,
            "total": row_count(parquet), "seed": seed}


def run_sql(parquet: Path, sql: str, limit: int = SQL_ROW_MAX, timeout: float = SQL_TIMEOUT) -> dict:
    body = sql.strip().rstrip(";").strip()
    if not body:
        raise QueryError("SQL 为空")
    bare = _COMMENTS.sub(" ", _STRINGS.sub("''", body))
    if ";" in bare:
        raise QueryError("只允许一条语句")
    if not _QUERY_START.match(bare):
        raise QueryError("只允许查询语句（SELECT / WITH / FROM），数据表名为 data")
    try:
        con = sandbox(parquet)
        described = con.execute(f"DESCRIBE SELECT * FROM ({body}) AS q").fetchall()
        _, rows = fetch(con, f"SELECT * FROM ({body}) AS q LIMIT {int(limit) + 1}", timeout=timeout)
    except QueryError:
        raise
    except Exception as exc:  # noqa: BLE001 — DuckDB 的语法/权限错误原样转成提示
        raise QueryError(str(exc).split("\n")[0]) from exc
    return {
        "columns": [{"name": r[0], "type": r[1], "kind": kind_of(r[1])} for r in described],
        "rows": [[None] + [jsonable(v) for v in r] for r in rows[:limit]],
        "truncated": len(rows) > limit,
    }
