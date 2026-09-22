"""公开卫生：已跟踪的文件里不能出现本机信息，版本号多处一致，私人目录不进版本库。

这些规则是仓库公开后每次提交都要守住的，写在一处，CI 每次都跑。
通用的检查（绝对路径、邮箱、密钥形状）写在这里；只有作者本机才知道的词
（私人项目名、目录名）放在 `.notes/hygiene_private_words.txt`（一行一个，不进版本库），
文件存在时一并检查。
"""
import json
import re
import subprocess
from pathlib import Path

import dsflow

REPO = Path(__file__).resolve().parent.parent
PRIVATE_WORDS = REPO / ".notes" / "hygiene_private_words.txt"

# 不允许出现的字符串：本机路径、邮箱、密钥形状
FORBIDDEN = [
    # Windows 绝对路径；放行 JSON 里的转义（如 "FINAL:\n"）与两个通用示例路径
    re.compile(r"[A-Z]:\\(?![nrtu\"\\])(?!work\\我的项目)(?!dsflow-src)"),
    re.compile(r"[A-Z]:/(?!work/)"),
    re.compile(r"/Users/[a-z]"),
    re.compile(r"/home/[a-z]"),
    re.compile(r"[A-Za-z0-9._%+-]+@(gmail|qq|outlook|163)\.com"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".css", ".md", ".yaml", ".yml", ".json", ".toml", ".html", ".ipynb", ".txt", ".cfg", ".ini"}
SKIP = {"uv.lock", "web/pnpm-lock.yaml", "tests/test_public_hygiene.py"}


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    return [REPO / p for p in out.decode("utf-8").split("\0") if p]


def forbidden_patterns() -> list[re.Pattern]:
    patterns = list(FORBIDDEN)
    if PRIVATE_WORDS.is_file():
        words = [w.strip() for w in PRIVATE_WORDS.read_text(encoding="utf-8").splitlines() if w.strip() and not w.startswith("#")]
        patterns.extend(re.compile(re.escape(w)) for w in words)
    return patterns


def test_tracked_text_files_carry_no_local_information():
    patterns = forbidden_patterns()
    hits = []
    for path in tracked_files():
        rel = path.relative_to(REPO).as_posix()
        if rel in SKIP or path.suffix not in TEXT_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pat in patterns:
            for m in pat.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{rel}:{line}: {m.group(0)}")
    assert not hits, "已跟踪文件里出现本机信息：\n" + "\n".join(hits[:40])


def test_private_dirs_are_ignored():
    ignore = {line.lstrip("/") for line in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()}
    for entry in (".notes/", ".claude/", ".dsflow_home/", ".venv/"):
        assert entry in ignore, f".gitignore 缺 {entry}"
    tracked = {p.relative_to(REPO).as_posix() for p in tracked_files()}
    assert not any(p.startswith((".notes/", ".claude/", ".dsflow_home/")) for p in tracked)


def test_versions_agree_in_three_places():
    py = re.search(r'^version = "([^"]+)"', (REPO / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    web = json.loads((REPO / "web" / "package.json").read_text(encoding="utf-8"))["version"]
    plugin = json.loads((REPO / "plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    assert py == dsflow.__version__ == web == plugin, (py, dsflow.__version__, web, plugin)
    changelog = (REPO / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {py} · " in changelog, f"CHANGELOG 里没有 {py} 的条目"
