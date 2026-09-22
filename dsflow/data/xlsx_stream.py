"""流式读取 xlsx：逐行解析工作表 XML，内存只占一个批次。

用途：DuckDB excel 扩展读不了的文件（例如导出工具把文字全部内嵌在单元格里、工作表 XML 解压后
上 GB 的情况）。所有单元格先按文本写入 Parquet，再由 convert.retype_text_columns 逐列推断类型。
日期样式的数值单元格按 Excel 序列号换算成 "YYYY-MM-DD HH:MM:SS"。
"""

from __future__ import annotations

import html
import posixpath
import re
import zipfile
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree.ElementTree import fromstring, iterparse

import pyarrow as pa
import pyarrow.parquet as pq

DATE_FORMAT_IDS = set(range(14, 23)) | {45, 46, 47}
EXCEL_EPOCH = datetime(1899, 12, 30)
BATCH_ROWS = 50_000
_LETTERS = re.compile(r"[A-Z]+")
_FORMAT_NOISE = re.compile(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.')

Progress = Callable[[float | None, str], None]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(elem, name: str) -> str | None:
    for key, value in elem.attrib.items():
        if _local(key) == name:
            return value
    return None


def _col_index(ref: str) -> int:
    m = _LETTERS.match(ref)
    n = 0
    for ch in m.group(0) if m else "A":
        n = n * 26 + ord(ch) - 64
    return n - 1


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    """读取某个部件的关系文件，返回 {关系 id: 目标部件的 zip 内路径}。"""
    folder, name = posixpath.split(part)
    rel_path = posixpath.join(folder, "_rels", name + ".rels")
    if rel_path not in z.namelist():
        return {}
    out = {}
    for rel in fromstring(z.read(rel_path)):
        target = rel.get("Target", "")
        resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        out[rel.get("Id")] = resolved
    return out


def _workbook_part(z: zipfile.ZipFile) -> str:
    for rel in fromstring(z.read("_rels/.rels")):
        if rel.get("Type", "").endswith("/officeDocument"):
            return rel.get("Target", "xl/workbook.xml").lstrip("/")
    return "xl/workbook.xml"


def list_sheets(path: Path) -> list[tuple[str, str]]:
    with zipfile.ZipFile(path) as z:
        wb_part = _workbook_part(z)
        rels = _rels(z, wb_part)
        wb = fromstring(z.read(wb_part))
        sheets = []
        for elem in wb.iter():
            if _local(elem.tag) == "sheet":
                target = rels.get(_attr(elem, "id") or "")
                if target:
                    sheets.append((elem.get("name", target), target))
        return sheets


def _shared_strings(z: zipfile.ZipFile, part: str | None) -> list[str]:
    if not part or part not in z.namelist():
        return []
    strings: list[str] = []
    with z.open(part) as f:
        for _, elem in iterparse(f):
            if _local(elem.tag) == "si":
                parts = []
                for child in elem:
                    kind = _local(child.tag)
                    if kind == "t":
                        parts.append(child.text or "")
                    elif kind == "r":
                        parts += [t.text or "" for t in child if _local(t.tag) == "t"]
                strings.append("".join(parts))
                elem.clear()
    return strings


def _date_styles(z: zipfile.ZipFile, part: str | None) -> set[int]:
    if not part or part not in z.namelist():
        return set()
    root = fromstring(z.read(part))
    custom = {}
    xfs: list[int] = []
    for elem in root:
        if _local(elem.tag) == "numFmts":
            for fmt in elem:
                custom[int(fmt.get("numFmtId", "0"))] = fmt.get("formatCode", "")
        elif _local(elem.tag) == "cellXfs":
            xfs = [int(xf.get("numFmtId", "0")) for xf in elem]
    dates = set()
    for i, fmt_id in enumerate(xfs):
        code = _FORMAT_NOISE.sub("", custom.get(fmt_id, "")).lower()
        if fmt_id in DATE_FORMAT_IDS or (fmt_id in custom and re.search(r"[ydhs]|m", code) and "general" not in code):
            dates.add(i)
    return dates


def _serial_to_text(value: str) -> str:
    try:
        moment = EXCEL_EPOCH + timedelta(days=float(value))
    except (ValueError, OverflowError):
        return value
    return moment.strftime("%Y-%m-%d %H:%M:%S")


class _CountingReader:
    def __init__(self, raw):
        self.raw, self.read_bytes = raw, 0

    def read(self, n: int = -1) -> bytes:
        data = self.raw.read(n)
        self.read_bytes += len(data)
        return data


_ROW_RE = re.compile(rb"<(?:\w+:)?row\b[^>]*?(?:/>|>(.*?)</(?:\w+:)?row>)", re.S)
_ROW_CLOSE_RE = re.compile(rb"</(?:\w+:)?row>|<(?:\w+:)?row\b[^>]*/>")
_CELL_RE = re.compile(rb"<(?:\w+:)?c\b([^>]*?)(?:/>|>(.*?)</(?:\w+:)?c>)", re.S)
_ATTR_RE = re.compile(rb'([\w:]+)\s*=\s*"([^"]*)"')
_V_RE = re.compile(rb"<(?:\w+:)?v>(.*?)</(?:\w+:)?v>", re.S)
_T_RE = re.compile(rb"<(?:\w+:)?t\b[^>]*?(?:/>|>(.*?)</(?:\w+:)?t>)", re.S)
_RPH_RE = re.compile(rb"<(?:\w+:)?rPh\b.*?</(?:\w+:)?rPh>", re.S)
_LETTERS_B = re.compile(rb"[A-Z]+")
CHUNK = 8 << 20


def _text(raw: bytes) -> str:
    s = raw.decode("utf-8", "replace")
    return html.unescape(s) if "&" in s else s


def _col_index_b(ref: bytes) -> int:
    m = _LETTERS_B.match(ref)
    n = 0
    for ch in m.group(0) if m else b"A":
        n = n * 26 + ch - 64
    return n - 1


def _last_row_end(buf: bytes) -> int:
    start = max(0, len(buf) - (1 << 20))
    while True:
        end = -1
        for m in _ROW_CLOSE_RE.finditer(buf, start):
            end = m.end()
        if end != -1 or start == 0:
            return end
        start = 0


def _rows_fast(raw, total: int, strings: list[str], dates: set[int],
               progress: Progress | None) -> Iterator[list[str | None]]:
    """正则快速路径：按块读解压后的 XML，只在完整的 </row> 处切分，内存只占一块。"""
    buf = b""
    read = last_report = 0
    while True:
        chunk = raw.read(CHUNK)
        if chunk:
            read += len(chunk)
            buf += chunk
            cut = _last_row_end(buf)
            if cut <= 0:
                continue
            region, buf = buf[:cut], buf[cut:]
        else:
            region, buf = buf, b""
        for row in _ROW_RE.finditer(region):
            content = row.group(1)
            cells: dict[int, str] = {}
            if content:
                for pos, c in enumerate(_CELL_RE.finditer(content)):
                    inner = c.group(2)
                    if not inner:
                        continue
                    attrs = dict(_ATTR_RE.findall(c.group(1)))
                    ref = attrs.get(b"r")
                    idx = _col_index_b(ref) if ref else pos
                    kind = attrs.get(b"t")
                    if kind == b"inlineStr":
                        body = _RPH_RE.sub(b"", inner) if b"rPh" in inner else inner
                        value = "".join(_text(t) for t in _T_RE.findall(body) if t)
                    else:
                        vm = _V_RE.search(inner)
                        if vm is None:
                            continue
                        v = _text(vm.group(1))
                        if kind == b"s":
                            value = strings[int(v)]
                        elif kind == b"b":
                            value = "TRUE" if v == "1" else "FALSE"
                        elif kind in (b"str", b"e", b"d"):
                            value = v
                        else:
                            style = attrs.get(b"s")
                            value = _serial_to_text(v) if style and int(style) in dates else v
                    if value != "":
                        cells[idx] = value
            width = max(cells) + 1 if cells else 0
            yield [cells.get(i) for i in range(width)]
        if progress and read - last_report > (64 << 20):
            last_report = read
            progress(min(0.95, read / total), f"逐行解析工作表（{read / total:.0%}）")
        if not chunk:
            return


def iter_rows(path: Path, sheet: int = 0, progress: Progress | None = None,
              fast: bool = True) -> Iterator[list[str | None]]:
    """逐行产出单元格文本（按列号对齐，空单元格为 None）。

    fast=True 用正则快速路径；fast=False 用 ElementTree 逐元素解析（更慢，作为对照实现）。
    """
    with zipfile.ZipFile(path) as z:
        wb_part = _workbook_part(z)
        rels = _rels(z, wb_part)
        by_type = {}
        wb_rels_path = posixpath.join(posixpath.dirname(wb_part), "_rels", posixpath.basename(wb_part) + ".rels")
        if wb_rels_path in z.namelist():
            for rel in fromstring(z.read(wb_rels_path)):
                by_type[rel.get("Type", "").rsplit("/", 1)[-1]] = rels.get(rel.get("Id"))
        strings = _shared_strings(z, by_type.get("sharedStrings"))
        dates = _date_styles(z, by_type.get("styles"))
        sheets = list_sheets(path)
        if not sheets:
            raise ValueError("工作簿里没有工作表")
        part = sheets[sheet][1]
        total = z.getinfo(part).file_size
        if fast:
            with z.open(part) as raw:
                yield from _rows_fast(raw, total, strings, dates, progress)
            return
        with z.open(part) as raw:
            reader = _CountingReader(raw)
            sheet_data = None
            last_report = 0
            for event, elem in iterparse(reader, events=("start", "end")):
                tag = _local(elem.tag)
                if event == "start":
                    if tag == "sheetData":
                        sheet_data = elem
                    continue
                if tag != "row":
                    continue
                cells: dict[int, str | None] = {}
                for pos, c in enumerate(elem):
                    ref = c.get("r")
                    idx = _col_index(ref) if ref else pos
                    kind = c.get("t")
                    value = None
                    if kind == "inlineStr":
                        value = "".join(t.text or "" for t in c.iter() if _local(t.tag) == "t")
                    else:
                        v = next((x.text for x in c if _local(x.tag) == "v"), None)
                        if v is not None:
                            if kind == "s":
                                value = strings[int(v)]
                            elif kind == "b":
                                value = "TRUE" if v == "1" else "FALSE"
                            elif kind in ("str", "e", "d"):
                                value = v
                            else:
                                style = c.get("s")
                                value = _serial_to_text(v) if style and int(style) in dates else v
                    if value is not None and value != "":
                        cells[idx] = value
                width = max(cells) + 1 if cells else 0
                yield [cells.get(i) for i in range(width)]
                elem.clear()
                if sheet_data is not None:
                    sheet_data.clear()
                if progress and reader.read_bytes - last_report > (32 << 20):
                    last_report = reader.read_bytes
                    progress(min(0.95, reader.read_bytes / total), f"逐行解析工作表（{reader.read_bytes / total:.0%}）")


def _header(first: list[str | None]) -> list[str]:
    names, seen = [], {}
    for i, raw in enumerate(first):
        name = (raw or "").strip() or f"列{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        names.append(name)
    return names


def stream_to_text_parquet(src: Path, dst: Path, progress: Progress | None = None, sheet: int = 0) -> dict:
    rows = iter_rows(src, sheet, progress)
    header = _header(next(rows, []))
    width = len(header)
    schema = pa.schema([(h, pa.string()) for h in header])
    batch: list[list] = []
    written = empty = overflow = 0

    def flush(writer: pq.ParquetWriter) -> None:
        columns = [pa.array([r[i] if i < len(r) else None for r in batch], pa.string()) for i in range(width)]
        writer.write_table(pa.Table.from_arrays(columns, schema=schema))
        batch.clear()

    with pq.ParquetWriter(dst, schema) as writer:
        for row in rows:
            if not any(v is not None for v in row):
                empty += 1
                continue
            if len(row) > width:
                overflow += sum(1 for v in row[width:] if v is not None)
                row = row[:width]
            batch.append(row)
            written += 1
            if len(batch) >= BATCH_ROWS:
                flush(writer)
        if batch or written == 0:
            flush(writer)
    return {"rows": written, "empty_rows_skipped": empty, "cells_beyond_header": overflow,
            "sheet": list_sheets(src)[sheet][0]}
