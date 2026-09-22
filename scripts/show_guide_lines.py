"""把每条行注和它指着的那行代码并排打出来，人工比一遍。

平台只查行号存不存在，查不了行注说的是不是那一行——这个脚本补的就是这个盲区。
用法：uv run python scripts/show_guide_lines.py <项目目录> [步骤]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dsflow.core.steps import revisions_of  # noqa: E402
from dsflow.explain.guide import load_guide, read_cells, resolve_notebook  # noqa: E402
from dsflow.index.db import open_for_write  # noqa: E402


def main(project_dir: str, only: str | None = None) -> int:
    project = open_for_write(Path(project_dir))
    reg, _ = project.load()
    if reg is None:
        print("注册表无法解析")
        return 1
    bad = 0
    for step in reg.steps:
        if only and step.id != only:
            continue
        for rev in revisions_of(step):
            guide, _, _, _ = load_guide(project, step, rev)
            if not guide:
                continue
            default = guide.get("notebook")
            for pi, part in enumerate(guide.get("parts") or [], 1):
                ref = part.get("notebook") or default
                for ci, note in enumerate(part.get("cells") or [], 1):
                    lines = note.get("lines") or []
                    if not lines:
                        continue
                    path = resolve_notebook(project, rev.dir, note.get("notebook") or ref)
                    cells = read_cells(project.resolve(path))
                    first = note["cell"][0] if isinstance(note["cell"], list) else note["cell"]
                    for line in lines:
                        at = line.get("cell") or first
                        src = cells[at - 1]["source"].splitlines()
                        n = line["line"]
                        code = src[n - 1].strip() if 1 <= n <= len(src) else "（行号越界）"
                        if not code or code.startswith("#"):
                            bad += 1
                        print(f"{step.id} {rev.id} 问题{pi}·第{ci}条 单元格{at} 行{n}")
                        print(f"    代码：{code[:90]}")
                        print(f"    行注：{line['note'][:90]}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:3]))
