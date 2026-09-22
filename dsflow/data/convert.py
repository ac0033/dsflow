"""CSV / XLSX → Parquet 缓存转换。全程流式，内存受 DuckDB 上限约束。

- CSV：先嗅探编码（UTF-8 / GB18030），非 UTF-8 的流式转码为临时文件；全量推断类型。
- XLSX：优先用 DuckDB excel 扩展（流式）；类型推断失败时按文本读出再逐列推断；
  扩展不可用时退回 calamine（整表载入内存，大文件可能吃内存，结果中注明）。
- 以 0 开头的数字串（编码、电话）保留为文本，不转成数值。
"""

from __future__ import annotations

import codecs
import os
from collections.abc import Callable
from pathlib import Path

import duckdb

from .engine import DataError, connect, ident, lit, scan

Progress = Callable[[float | None, str], None]


def _noop(_fraction: float | None, _message: str) -> None:
    pass


def sniff_encoding(path: Path, probe: int = 1 << 20) -> str:
    raw = path.read_bytes()[:probe] if path.stat().st_size <= probe else _head(path, probe)
    for enc in ("utf-8-sig", "gb18030"):
        try:
            codecs.getincrementaldecoder(enc)().decode(raw, final=False)
            return "utf-8" if enc == "utf-8-sig" else enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def _head(path: Path, n: int) -> bytes:
    with open(path, "rb") as f:
        return f.read(n)


def _transcode(src: Path, dst: Path, encoding: str) -> None:
    decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
    with open(src, "rb") as fin, open(dst, "w", encoding="utf-8", newline="") as fout:
        while block := fin.read(1 << 20):
            fout.write(decoder.decode(block))
        fout.write(decoder.decode(b"", final=True))


def csv_to_parquet(src: Path, dst: Path, progress: Progress = _noop) -> dict:
    encoding = sniff_encoding(src)
    source = src
    staged: Path | None = None
    if encoding != "utf-8":
        progress(None, f"转码 {encoding} → UTF-8")
        staged = dst.with_suffix(".utf8.csv")
        _transcode(src, staged, encoding)
        source = staged
    progress(None, "读取 CSV 并写入 Parquet")
    try:
        con = connect()
        con.execute(
            f"COPY (SELECT * FROM read_csv({lit(source)}, header=true, sample_size=-1)) "
            f"TO {lit(dst)} (FORMAT parquet)"
        )
    finally:
        if staged and staged.exists():
            staged.unlink()
    return {"source_format": "csv", "encoding": encoding}


def _ensure_excel(con: duckdb.DuckDBPyConnection) -> bool:
    for stmt in ("LOAD excel", "INSTALL excel"):
        try:
            con.execute(stmt)
            if stmt == "INSTALL excel":
                con.execute("LOAD excel")
            return True
        except duckdb.Error:
            continue
    return False


def retype_text_columns(con: duckdb.DuckDBPyConnection, text_parquet: Path, dst: Path) -> list[str]:
    """把全文本的 Parquet 逐列推断为数值 / 时间 / 文本，返回仍保留为文本的列。"""
    columns = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {scan(text_parquet)}").fetchall()]
    checks = []
    for c in columns:
        q = ident(c)
        checks += [
            f"count({q})",
            f"count(TRY_CAST({q} AS DOUBLE))",
            f"count(TRY_CAST({q} AS TIMESTAMP))",
            f"count(*) FILTER (WHERE regexp_matches({q}, '^[+-]?0[0-9]'))",
            f"count(*) FILTER (WHERE regexp_matches({q}, '^[+-]?[0-9]+$') AND TRY_CAST({q} AS BIGINT) IS NOT NULL)",
        ]
    counts = con.execute(f"SELECT {', '.join(checks)} FROM {scan(text_parquet)}").fetchone()
    exprs, kept_text = [], []
    for i, c in enumerate(columns):
        non_null, as_double, as_ts, leading_zero, as_int = counts[5 * i: 5 * i + 5]
        q = ident(c)
        if non_null and as_int == non_null and leading_zero == 0:
            # 纯整数（如商品编号）用整数保存，避免浮点丢精度
            exprs.append(f"TRY_CAST({q} AS BIGINT) AS {q}")
        elif non_null and as_double == non_null and leading_zero == 0:
            exprs.append(f"TRY_CAST({q} AS DOUBLE) AS {q}")
        elif non_null and as_ts == non_null:
            exprs.append(f"TRY_CAST({q} AS TIMESTAMP) AS {q}")
        else:
            exprs.append(q)
            kept_text.append(c)
    con.execute(f"COPY (SELECT {', '.join(exprs)} FROM {scan(text_parquet)}) TO {lit(dst)} (FORMAT parquet)")
    return kept_text


def xlsx_to_parquet(src: Path, dst: Path, progress: Progress = _noop) -> dict:
    """先用 DuckDB 直接读；失败（结构不标准、同列类型混杂）就流式逐行解析再逐列推断。只读第一个工作表。

    不用 DuckDB 的 all_varchar 兜底：那样日期单元格会变成 Excel 序号（如 45658）而丢掉日期含义。
    """
    from .xlsx_stream import list_sheets, stream_to_text_parquet

    sheets = [name for name, _ in list_sheets(src)]
    sheet = sheets[0] if sheets else None
    meta = {"source_format": "xlsx", "sheet": sheet, "sheets": sheets}
    con = connect()
    text = dst.with_suffix(".text.parquet")
    errors = []
    try:
        if _ensure_excel(con):
            sheet_arg = f", sheet={lit(sheet)}" if sheet else ""
            try:
                progress(None, f"读取工作表「{sheet}」")
                con.execute(f"COPY (SELECT * FROM read_xlsx({lit(src)}{sheet_arg})) TO {lit(dst)} (FORMAT parquet)")
                return {**meta, "reader": "duckdb-excel"}
            except duckdb.Error as exc:
                errors.append(str(exc).split("\n")[0])
        progress(None, "逐行流式解析工作表")
        stats = stream_to_text_parquet(src, text, progress)
        progress(0.97, "逐列推断类型")
        kept = retype_text_columns(con, text, dst)
        return {**meta, "reader": "stream", "text_columns": kept, **stats,
                "note": "；".join(errors) or "excel 扩展不可用"}
    finally:
        if text.exists():
            text.unlink()


def convert(src: Path, fmt: str, dst: Path, progress: Progress = _noop) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + f".tmp{os.getpid()}.parquet")
    try:
        if fmt == "csv":
            meta = csv_to_parquet(src, tmp, progress)
        elif fmt == "xlsx":
            meta = xlsx_to_parquet(src, tmp, progress)
        else:
            raise DataError(f"不支持转换 {fmt}")
        os.replace(tmp, dst)
        return meta
    except duckdb.Error as exc:
        raise DataError(f"转换失败：{exc}") from exc
    finally:
        if tmp.exists():
            tmp.unlink()
