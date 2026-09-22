"""Claude Code hook：改完导读就体检，不通过就拦住。

装在被管项目的 .claude/settings.json（`dsflow attach` 负责装）：Write / Edit 一落到 guide.yaml
或平台目录的 guides/<步骤>/<轮次>.yaml，就对那一个步骤跑 `dsflow guide lint`。有问题时退出码 2，
Claude 会看到 stderr 里的清单并必须改，不能自己决定放过——用词和篇幅这两件事已经反复返工过，靠自觉不行。
"""

from __future__ import annotations

import re
from pathlib import Path

PLATFORM_GUIDE = re.compile(r"[/\\]projects[/\\]([0-9a-f]{10})[/\\]guides[/\\]([^/\\]+)[/\\][^/\\]+\.ya?ml$")
HOOK_MARKER = "-m dsflow hook guide-lint"


def hook_command(python: Path) -> str:
    """写进 settings.json 的命令：绝对路径的解释器 + `-m dsflow`，不依赖 PATH 和当前目录。"""
    return f'"{Path(python).resolve().as_posix()}" -X utf8 {HOOK_MARKER}'


def target(path: Path) -> tuple[Path, str | None] | None:
    """导读文件 →（项目目录, 步骤编号）。不是导读就返回 None。"""
    m = PLATFORM_GUIDE.search(str(path))
    if m:
        from .index.db import PlatformIndex

        row = PlatformIndex().get_project(m.group(1))
        return (Path(row["root"]), m.group(2)) if row else None
    if path.name == "guide.yaml":
        for parent in path.parents:
            if (parent / "dsflow.yaml").is_file():
                return parent, None
    return None


def guide_lint(event: dict) -> tuple[int, str]:
    """（退出码, 给 stderr 的文字）。0 = 放行；2 = 拦住并要求修改。"""
    raw = (event.get("tool_input") or {}).get("file_path") if isinstance(event, dict) else None
    if not raw:
        return 0, ""
    found = target(Path(raw))
    if found is None:
        return 0, ""
    project_dir, step = found

    from .core.project import ProjectError
    from .explain.lint import lint_project
    from .index.db import open_for_write

    try:
        project = open_for_write(project_dir)
        reg, _ = project.load()
    except ProjectError as exc:
        return 0, f"导读体检跑不起来：{exc}"
    if reg is None:
        return 0, ""
    issues = [(s, r, i) for s, r, i in lint_project(project, reg, step) if i]
    if not issues:
        return 0, ""
    lines = [f"导读体检没通过（{Path(raw).name}）。这些地方必须改掉再往下走："]
    for step_id, rev_id, found_issues in issues:
        lines.append(f"{step_id} {rev_id}：")
        lines += [f"  - {x}" for x in found_issues]
    lines.append("改完重新写一次这个文件即可；用词按 vocabulary.json，篇幅按提示压。")
    return 2, "\n".join(lines)
