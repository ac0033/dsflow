"""项目的分析环境：agent 执行 notebook 与脚本时用的那个 Python。

平台自己的解释器里只有 dsflow 的依赖（没有 pandas），项目自己的 `.venv` 里又没有 dsflow
（`python -m dsflow.tracking.notebook` 起不来）。两边缺一个，agent 一执行代码就报错。

这里把两边接上：用平台同一个解释器在项目里建 `.venv`（保证扩展模块的 ABI 一致），装基础分析库，
再写一个 `dsflow.pth` 把平台自己的 dsflow 挂进这个环境——不复制第二份，版本永远跟平台一致。
`.pth` 里的路径排在项目自己的包后面，所以项目装了哪个版本的库就用哪个。
"""

from __future__ import annotations

import shutil
import site
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from .paths import PACKAGE_DIR

DEFAULT_LIBS = ("pandas", "matplotlib", "scikit-learn", "openpyxl")
PTH_NAME = "dsflow.pth"


class EnvError(Exception):
    """准备环境失败：带上让用户能重跑的那条命令。"""


def venv_dir(root: Path) -> Path:
    return Path(root) / ".venv"


def venv_python(root: Path) -> Path | None:
    """项目自己的解释器，没有就返回 None。"""
    for rel in ("Scripts/python.exe", "bin/python"):
        exe = venv_dir(root) / rel
        if exe.is_file():
            return exe
    return None


def site_packages(root: Path) -> Path | None:
    for pattern in ("Lib/site-packages", "lib/python*/site-packages"):
        for hit in sorted(venv_dir(root).glob(pattern)):
            if hit.is_dir():
                return hit
    return None


def dsflow_roots() -> list[str]:
    """要挂进项目环境的目录：dsflow 包所在处 + 平台解释器的 site-packages（dsflow 的依赖在那里）。"""
    roots = [str(PACKAGE_DIR.parent)]
    for path in site.getsitepackages():
        if Path(path).is_dir() and path not in roots:
            roots.append(path)
    return roots


def status(root: Path) -> dict:
    """给 doctor 用的便宜检查：只看目录和文件，不启动解释器。"""
    root = Path(root)
    packages = site_packages(root)
    pth = packages / PTH_NAME if packages else None
    installed = sorted(p.name for p in packages.iterdir() if p.is_dir() and not p.name.endswith(".dist-info")) if packages else []
    linked: list[str] = []
    if pth and pth.is_file():
        linked = [line for line in pth.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {
        "venv": venv_python(root) is not None,
        "python": str(venv_python(root)) if venv_python(root) else "",
        "dsflow_linked": bool(linked) and all(Path(line).is_dir() for line in linked),
        "linked_to": linked,
        "libs": [lib for lib in ("pandas", "matplotlib", "sklearn", "openpyxl") if lib in installed],
    }


def _run(argv: list[str], what: str) -> None:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise EnvError(f"{what}失败：{exc}") from None
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        raise EnvError(f"{what}失败：" + " / ".join(tail))


def link_dsflow(root: Path) -> Path:
    """把平台的 dsflow 挂进项目环境，返回写出的 .pth 文件。"""
    packages = site_packages(root)
    if packages is None:
        raise EnvError(f"{venv_dir(root)} 里没有 site-packages，环境没建成")
    pth = packages / PTH_NAME
    pth.write_text("\n".join(dsflow_roots()) + "\n", encoding="utf-8")
    return pth


def prepare(root: Path, libs: tuple[str, ...] | None = None, seed: bool = True) -> Iterator[str]:
    """建 .venv、装分析库、挂上 dsflow。每做完一件事就 yield 一行给用户看。

    seed=False 只给测试用：不往新环境里装 pip，省下每次几十秒的下载。
    """
    root = Path(root).resolve()
    libs = DEFAULT_LIBS if libs is None else libs
    uv = shutil.which("uv")
    if venv_python(root) is None:
        if uv:
            # --seed 装上 pip：agent 与用户习惯敲 pip install，uv 建的环境默认没有它
            _run([uv, "venv", *(["--seed"] if seed else []), "--python", sys.executable, str(venv_dir(root))], "建虚拟环境")
        else:
            _run([sys.executable, "-m", "venv", str(venv_dir(root))], "建虚拟环境")
        yield f"分析环境：已建 {venv_dir(root)}（Python {sys.version.split()[0]}，和平台同一个）"
    else:
        yield f"分析环境：已有 {venv_dir(root)}，直接用"
    python = venv_python(root)
    if python is None:
        raise EnvError(f"建完 {venv_dir(root)} 还是找不到解释器")
    if libs:
        if uv:
            _run([uv, "pip", "install", "--python", str(python), *libs], "装分析库")
        else:
            _run([str(python), "-m", "pip", "install", "--quiet", *libs], "装分析库")
        yield f"分析环境：已装 {'、'.join(libs)}"
    link_dsflow(root)
    yield "分析环境：已把平台的 dsflow 挂进去（notebook 执行器与 SDK 可用）"


# ---------- 开工前的自检 ----------

IMPORT_NAMES = {"scikit-learn": "sklearn", "pillow": "PIL", "opencv-python": "cv2"}
BASE_IMPORTS = ("dsflow", "dsflow.tracking.notebook")
_PROBE = (
    "import json, sys\n"
    "out = {}\n"
    "for name in sys.argv[1:]:\n"
    "    try:\n"
    "        __import__(name)\n"
    "        out[name] = ''\n"
    "    except Exception as exc:\n"
    "        out[name] = f'{type(exc).__name__}: {exc}'\n"
    "print(json.dumps(out))\n"
)


def import_name(lib: str) -> str:
    """装的时候写库名（scikit-learn），import 的时候写模块名（sklearn）。"""
    return IMPORT_NAMES.get(lib.lower(), lib.replace("-", "_"))


def fix_command(root: Path) -> str:
    return f'dsflow attach "{Path(root).resolve()}" --venv'


def _importable_from(dirs: list[str], name: str) -> bool:
    """在这些目录里能不能找到这个模块（只看文件名，不启动解释器）。"""
    return any((Path(d) / name).is_dir() or (Path(d) / f"{name}.py").is_file() for d in dirs)


def quick_check(root: Path) -> dict:
    """只看目录和文件的快检查（`next` 每次都要跑，所以不启动解释器）。

    项目环境里的 `dsflow.pth` 把平台的 site-packages 也挂了进来，所以一个库装在平台那边同样能 import；
    这里两处都找，结论才和真的启动解释器的 `check` 一致。
    """
    st = status(root)
    lacking = [lib for lib in DEFAULT_LIBS
               if import_name(lib) not in st["libs"] and not _importable_from(st["linked_to"], import_name(lib))]
    if not st["venv"]:
        detail = "项目里没有 .venv：agent 执行代码会用平台自己的解释器，那里没有 pandas。"
    elif not st["dsflow_linked"]:
        detail = f"{venv_dir(root)} 在，但里面没有挂上平台的 dsflow：执行 notebook 会报 No module named 'dsflow'。"
    elif lacking:
        detail = f"{venv_dir(root)} 和平台的环境里都没有这些库：{'、'.join(lacking)}。"
    else:
        detail = f"{venv_dir(root)} 建好了，平台的 dsflow 已挂进去，基础分析库齐全。"
    return {"ready": bool(st["venv"] and st["dsflow_linked"] and not lacking), "detail": detail,
            "fix": "" if st["venv"] and st["dsflow_linked"] and not lacking else fix_command(root)}


def check(root: Path, imports: list[str] | None = None, timeout: int = 120) -> dict:
    """开工前的环境自检：有没有 .venv、平台的 dsflow 挂没挂进去、要用的库能不能真的 import 进来。

    比 `quick_check` 慢：它真的启动项目自己的解释器 import 一遍，装了一半、版本装坏的库也能查出来。
    """
    import json

    root = Path(root).resolve()
    checks: list[dict] = []
    fix = fix_command(root)
    python = venv_python(root)
    if python is None:
        checks.append({"name": "分析环境", "status": "fail", "detail": f"{venv_dir(root)} 不存在：项目还没有自己的解释器。", "fix": fix})
        return {"ready": False, "python": "", "checks": checks, "fix": fix}
    checks.append({"name": "分析环境", "status": "ok", "detail": f"项目的解释器是 {python}。", "fix": ""})
    wanted = list(BASE_IMPORTS) + [import_name(lib) for lib in DEFAULT_LIBS] + [import_name(m) for m in (imports or [])]
    seen: list[str] = []
    for name in wanted:
        if name not in seen:
            seen.append(name)
    try:
        proc = subprocess.run([str(python), "-c", _PROBE, *seen], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        checks.append({"name": "启动解释器", "status": "fail", "detail": f"{python} 跑不起来：{exc}", "fix": fix})
        return {"ready": False, "python": str(python), "checks": checks, "fix": fix}
    try:
        result = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        checks.append({"name": "启动解释器", "status": "fail", "detail": "自检脚本没有返回结果：" + " / ".join(tail), "fix": fix})
        return {"ready": False, "python": str(python), "checks": checks, "fix": fix}
    for name in seen:
        error = result.get(name, "没有检查到这个模块。")
        if not error:
            checks.append({"name": f"import {name}", "status": "ok", "detail": f"{name} 能 import。", "fix": ""})
        elif name in BASE_IMPORTS:
            checks.append({"name": f"import {name}", "status": "fail",
                           "detail": f"{name} import 不进来：{error}平台的 dsflow 没有挂进这个环境。", "fix": fix})
        else:
            lib = next((b for b in (*DEFAULT_LIBS, *(imports or [])) if import_name(b) == name), name)
            checks.append({"name": f"import {name}", "status": "fail", "detail": f"{name} import 不进来：{error}",
                           "fix": f'"{python}" -m pip install {lib}'})
    ready = not any(c["status"] == "fail" for c in checks)
    return {"ready": ready, "python": str(python), "checks": checks,
            "fix": "" if ready else next(c["fix"] for c in checks if c["status"] == "fail")}
