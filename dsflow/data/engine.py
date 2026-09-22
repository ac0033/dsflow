"""DuckDB 连接与通用工具。

所有查询共用一套内存上限、线程数和溢写目录（默认 1GB / 4 线程，可用环境变量调整），
保证在内存紧张的机器上处理 GB 级数据时不会把系统拖垮。
"""

from __future__ import annotations

import math
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

from ..paths import dsflow_home

JS_SAFE_INT = 2**53
NUMERIC_TYPES = {
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER",
    "UBIGINT", "UHUGEINT", "FLOAT", "DOUBLE", "REAL",
}


class DataError(Exception):
    pass


class QueryError(DataError):
    pass


def memory_limit() -> str:
    return os.environ.get("DSFLOW_DUCKDB_MEMORY", "1GB")


def threads() -> int:
    return int(os.environ.get("DSFLOW_DUCKDB_THREADS", "4"))


_SLOTS = threading.BoundedSemaphore(int(os.environ.get("DSFLOW_DUCKDB_SLOTS", "3")))


@contextmanager
def slot() -> Iterator[None]:
    """同时运行的重查询个数上限（默认 3）。每个 DuckDB 连接有自己的内存上限，
    不限并发的话，几个排序或对比同时跑，内存会成倍增加。"""
    with _SLOTS:
        yield


def temp_dir() -> Path:
    path = dsflow_home() / "tmp" / "duckdb"
    path.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(config={
        "memory_limit": memory_limit(),
        "threads": threads(),
        "temp_directory": temp_dir().as_posix(),
    })


def ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def lit(value: str | Path) -> str:
    text = value.as_posix() if isinstance(value, Path) else value
    return "'" + text.replace("'", "''") + "'"


def scan(path: Path) -> str:
    return f"read_parquet({lit(path)})"


def sandbox(parquet: Path) -> duckdb.DuckDBPyConnection:
    """只读 SQL 连接：只能看到名为 data 的视图；不能读其他文件、写文件、装扩展或改配置。"""
    con = connect()
    con.execute(f"CREATE VIEW data AS SELECT * FROM {scan(parquet)}")
    con.execute(f"SET allowed_paths=[{lit(parquet)}]")
    con.execute(f"SET allowed_directories=[{lit(temp_dir())}]")
    con.execute("SET enable_external_access=false")
    con.execute("SET lock_configuration=true")
    return con


def fetch(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None,
          timeout: float | None = None) -> tuple[list[str], list[tuple]]:
    timer = threading.Timer(timeout, con.interrupt) if timeout else None
    if timer:
        timer.start()
    try:
        cur = con.execute(sql, params or [])
        return [d[0] for d in cur.description], cur.fetchall()
    except duckdb.InterruptException as exc:
        raise QueryError(f"查询超过 {timeout:g} 秒，已中止") from exc
    finally:
        if timer:
            timer.cancel()


def kind_of(duck_type: str) -> str:
    t = duck_type.upper()
    if t in NUMERIC_TYPES or t.startswith(("DECIMAL", "NUMERIC")):
        return "numeric"
    if t.startswith(("TIMESTAMP", "DATE")):
        return "temporal"
    if t == "BOOLEAN":
        return "boolean"
    if t.startswith("VARCHAR") or t == "UUID":
        return "text"
    return "other"


def jsonable(v):
    """把 DuckDB 返回值转成前端能安全显示的 JSON 值。超出 JS 安全整数范围的整数转成字符串。"""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return str(v) if abs(v) >= JS_SAFE_INT else v
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, (date, time)):
        return v.isoformat()
    if isinstance(v, timedelta):
        return str(v)
    if isinstance(v, bytes):
        return f"<{len(v)} 字节>"
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    return str(v)


def to_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f
