"""活动流：git 提交（只看改动了本项目目录的）、运行、轮次、问题与决策，按时间倒序合在一起。"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from ..core.schemas import Registry
from ..core.steps import revisions_of

_STEP = re.compile(r"step\s*(\d+\.\d+)(?:\s+(r\d+))?", re.I)
RUN_LABEL = {"succeeded": "运行成功", "failed": "运行失败", "running": "运行中"}


def git_commits(root: Path, limit: int = 200) -> list[dict]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", f"-n{limit}", "--date=iso-strict", "--pretty=format:%h%x1f%ad%x1f%s", "--", "."],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    commits = []
    for line in out.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        sha, date, subject = parts
        m = _STEP.search(subject)
        local = datetime.fromisoformat(date).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
        commits.append({"time": local, "kind": "commit", "title": subject, "ref": sha,
                        "step": m.group(1) if m else None, "revision": m.group(2) if m and m.group(2) else None})
    return commits


def activity(root: Path, reg: Registry, runs: list[dict], tracker: dict[str, list[dict]], limit: int = 60) -> list[dict]:
    events = git_commits(root)
    for r in runs:
        events.append({"time": r["started_at"], "kind": "run", "status": r["status"], "step": r["step"],
                       "ref": r["run_id"], "title": f"{RUN_LABEL.get(r['status'], r['status'])}：{r.get('conclusion') or r.get('hypothesis') or r.get('error') or ''}"})
    for step in reg.steps:
        for rev in revisions_of(step):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", Path(rev.dir).name)
            if m:
                events.append({"time": m.group(1), "kind": "revision", "step": step.id, "revision": rev.id,
                               "title": f"{step.id} {rev.id} 开始：{rev.summary}"})
    for item in tracker.get("issues", []):
        events.append({"time": item["created_at"], "kind": "issue", "step": item.get("step"), "ref": item["id"],
                       "title": f"记录问题 {item['id']}：{item['title']}"})
        if item.get("resolved_at"):
            events.append({"time": item["resolved_at"], "kind": "issue", "step": item.get("step"), "ref": item["id"],
                           "title": f"解决问题 {item['id']}：{item['title']}"})
    for item in tracker.get("decisions", []):
        events.append({"time": item.get("created_at") or item["date"], "kind": "decision", "step": item.get("step"),
                       "ref": item["id"], "title": f"决策 {item['id']}：{item['title']}"})
    for item in tracker.get("pending", []):
        if item.get("resolved_at"):
            events.append({"time": item["resolved_at"], "kind": "pending", "step": item.get("step"), "ref": item["id"],
                           "title": f"裁定 {item['id']}：{item['question']} → {item.get('resolved_answer') or ''}"})
    events.sort(key=lambda e: e["time"], reverse=True)
    return events[:limit]
