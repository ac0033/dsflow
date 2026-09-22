"""只看前几行几列：讲解旁边的数据视图用它。

和 browse 的区别是**不建缓存、不整表转换**：xlsx 逐行解析、读满就停（243 MB 的采购单取 5 行约 0.04 秒），
parquet 直接 LIMIT。整表转 Parquet 那条路留给数据页的浏览与画像（145 MB 的文件要跑 5 分多钟），
数据视图不走它，所以每一步都配得起。
"""

from __future__ import annotations

import csv
from itertools import islice
from pathlib import Path

from ..core.project import Project
from .engine import DataError, connect, ident, jsonable, scan
from .files import data_format
from .xlsx_stream import iter_rows

MAX_ROWS = 20
MAX_COLUMNS = 8


def _pick(header: list[str], wanted: list[str]) -> list[int]:
    """要看的列 → 在表头里的下标。写错的列名直接报出来，不要静悄悄少一列。"""
    if not wanted:
        return list(range(min(len(header), MAX_COLUMNS)))
    index = {name: i for i, name in enumerate(header)}
    missing = [w for w in wanted if w not in index]
    if missing:
        raise DataError(f"这份数据里没有这些列：{'、'.join(missing)}")
    return [index[w] for w in wanted[:MAX_COLUMNS]]


def _delimiter(first_line: str) -> str:
    """按表头里哪个分隔符最多来定：逗号、分号、制表符都常见（Vinho Verde 那两份 CSV 就是分号分隔的）。"""
    counts = {d: first_line.count(d) for d in (",", ";", "\t")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def _csv_head(path: Path, limit: int) -> tuple[list[str], list[list]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        first = fh.readline()
        fh.seek(0)
        rows = list(islice(csv.reader(fh, delimiter=_delimiter(first)), limit + 1))
    return (rows[0] if rows else []), rows[1:]


def _xlsx_head(path: Path, limit: int, sheet: int) -> tuple[list[str], list[list]]:
    rows = []
    it = iter_rows(path, sheet=sheet)
    try:
        for i, row in enumerate(it):
            rows.append(row)
            if i >= limit:
                break
    finally:
        it.close()
    header = [str(c) if c is not None else f"列{i + 1}" for i, c in enumerate(rows[0])] if rows else []
    return header, rows[1:]


def _parquet_head(path: Path, limit: int, wanted: list[str]) -> tuple[list[str], list[list], list[str]]:
    con = connect()
    header = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {scan(path)}").fetchall()]
    take = [header[i] for i in _pick(header, wanted)]
    select = ", ".join(ident(c) for c in take)
    rows = con.execute(f"SELECT {select} FROM {scan(path)} LIMIT {int(limit)}").fetchall()
    return take, [list(r) for r in rows], header


def peek(project: Project, rel: str, columns: list[str] | None = None, limit: int = 5,
         sheet: int = 0) -> dict:
    """一份数据文件的前几行、只取要看的列。返回的 rows 已经是可 JSON 化的文字/数字。"""
    limit = max(1, min(int(limit), MAX_ROWS))
    wanted = [c for c in (columns or []) if c]
    path = project.resolve(rel)
    if not path.is_file():
        raise FileNotFoundError(rel)
    fmt = data_format(path)
    if fmt is None:
        raise DataError(f"不支持的数据格式：{path.suffix or '无后缀'}（支持 csv / tsv / xlsx / parquet）")

    if fmt == "parquet":
        header, rows, all_columns = _parquet_head(path, limit, wanted)
    else:
        all_columns, rows = (_xlsx_head(path, limit, sheet) if fmt == "xlsx" else _csv_head(path, limit))
        keep = _pick(all_columns, wanted)
        header = [all_columns[i] for i in keep]
        rows = [[r[i] if i < len(r) else None for i in keep] for r in rows]

    return {
        "path": rel,
        "format": fmt,
        "columns": header,
        "rows": [[jsonable(v) for v in row] for row in rows],
        "limit": limit,
        "total_columns": len(all_columns),
        # 全部列名：只看前 8 列写不出 SQL，也数不清这张表有哪些字段
        "all_columns": all_columns,
        "size": path.stat().st_size,
    }
