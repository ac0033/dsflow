"""平台自带的 notebook 执行器：在当前进程里逐格执行代码单元格，把输出写回 notebook 文件。

不需要 Jupyter 内核（离线装不上 nbclient / ipykernel 时也能用），代价是不支持 IPython 魔法命令（% 或 ! 开头的行）。

    python -m dsflow.tracking.notebook <notebook> [--param 名=值 …] [--save-to 另存路径] [--cwd 工作目录]

由 `dsflow run <步骤> -- python -m dsflow.tracking.notebook <notebook>` 启动时，notebook 里的 dsflow SDK
写进同一条运行记录。--param 会在带 parameters 标签的单元格之后插入一个参数单元格（沿用 papermill 的约定），
值按 Python 字面量解析，解析不了就当字符串；上一次注入的参数单元格会被替换掉，不会越积越多。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

INJECTED = "injected-parameters"


def _text(value) -> str:
    return "".join(value) if isinstance(value, list) else (value or "")


def _tags(cell: dict) -> list[str]:
    return list((cell.get("metadata") or {}).get("tags") or [])


class _Tee:
    """单元格的打印输出：既写进 notebook，也照原样打到真正的输出（`dsflow run` 的日志里看得到）。"""

    def __init__(self, outputs: list[dict], name: str, real) -> None:
        self.outputs, self.name, self.real = outputs, name, real

    def write(self, text: str) -> int:
        if text:
            last = self.outputs[-1] if self.outputs else None
            if last and last.get("output_type") == "stream" and last["name"] == self.name:
                last["text"] += text
            else:
                self.outputs.append({"output_type": "stream", "name": self.name, "text": text})
            self.real.write(text)
        return len(text)

    def flush(self) -> None:
        self.real.flush()


def _bundle(value: Any) -> dict:
    """一个值的显示形式：纯文本必给，有 _repr_html_ 的（如 DataFrame）再给一份 HTML。"""
    data = {"text/plain": repr(value)}
    render = getattr(value, "_repr_html_", None)
    if callable(render):
        try:
            html = render()
        except Exception:  # noqa: BLE001 — 富显示失败不影响执行，退回纯文本
            html = None
        if isinstance(html, str):
            data["text/html"] = html
    return data


def run_cell(source: str, ns: dict, outputs: list[dict], count: int) -> str | None:
    """执行一个代码单元格；输出写进 outputs，出错时返回错误摘要（和 Jupyter 一样把错误留在 notebook 里）。"""

    def display(value: Any) -> None:
        if value is not None:
            outputs.append({"output_type": "display_data", "data": _bundle(value), "metadata": {}})

    ns["display"] = display
    out, err = _Tee(outputs, "stdout", sys.stdout), _Tee(outputs, "stderr", sys.stderr)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            tree = ast.parse(source)
            last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
            exec(compile(tree, "<单元格>", "exec"), ns)  # noqa: S102 — 执行 notebook 本身就是执行项目自己的代码
            if last is not None:
                value = eval(compile(ast.Expression(last.value), "<单元格>", "eval"), ns)  # noqa: S307
                if value is not None:
                    outputs.append({"output_type": "execute_result", "execution_count": count,
                                    "data": _bundle(value), "metadata": {}})
    except BaseException as exc:  # noqa: BLE001 — 单元格里的任何错误都如实写进 notebook
        outputs.append({
            "output_type": "error", "ename": type(exc).__name__, "evalue": str(exc),
            "traceback": [line.rstrip("\n") for line in traceback.format_exception(exc)],
        })
        return f"{type(exc).__name__}: {exc}"
    return None


def execute(path: Path, params: dict[str, Any] | None = None, save_to: Path | None = None,
            cwd: Path | None = None) -> dict:
    """逐格执行并保存。默认工作目录是 notebook 所在目录（和 Jupyter 一致）；某一格报错后面的格子不再执行。"""
    nb = json.loads(path.read_text(encoding="utf-8"))
    cells = [c for c in nb.get("cells", []) if INJECTED not in _tags(c)]
    if params:
        at = next((i for i, c in enumerate(cells) if "parameters" in _tags(c)), -1)
        body = "# 本次运行传入的参数（dsflow）\n" + "".join(f"{k} = {v!r}\n" for k, v in params.items())
        cells.insert(at + 1, {"cell_type": "code", "metadata": {"tags": [INJECTED]}, "source": body,
                              "execution_count": None, "outputs": []})
    nb["cells"] = cells
    ns: dict[str, Any] = {"__name__": "__main__", "__file__": str(path)}
    here = Path.cwd()
    os.chdir(cwd or path.parent)
    count, error, failed_at = 0, None, None
    try:
        for cell in cells:
            if cell.get("cell_type") != "code":
                continue
            count += 1
            if error is not None:
                cell["execution_count"], cell["outputs"] = None, []
                continue
            outputs: list[dict] = []
            cell["execution_count"], cell["outputs"] = count, outputs
            error = run_cell(_text(cell.get("source")), ns, outputs, count)
            if error:
                failed_at = count
    finally:
        os.chdir(here)
        target = save_to or path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"cells": count, "failed_at": failed_at, "error": error, "saved": str(save_to or path)}


def _value(text: str) -> Any:
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="执行 notebook 并把输出写回文件（不需要 Jupyter 内核）")
    parser.add_argument("notebook", type=Path)
    parser.add_argument("--param", action="append", default=[], metavar="名=值", help="注入参数")
    parser.add_argument("--save-to", type=Path, default=None, help="另存到别处，默认原地保存")
    parser.add_argument("--cwd", type=Path, default=None, help="工作目录，默认 notebook 所在目录")
    args = parser.parse_args(argv)
    params = {}
    for item in args.param:
        if "=" not in item:
            parser.error(f"参数要写成 名=值：{item}")
        name, _, text = item.partition("=")
        params[name.strip()] = _value(text)
    result = execute(args.notebook.resolve(), params, args.save_to, args.cwd)
    if result["error"]:
        print(f"notebook 第 {result['failed_at']} 个代码单元格报错：{result['error']}（已写回 {result['saved']}）")
        return 1
    print(f"notebook 执行完成：{result['cells']} 个代码单元格全部成功，已写回 {result['saved']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
