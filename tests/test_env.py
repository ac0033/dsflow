"""项目的分析环境：建 .venv、挂上平台的 dsflow，doctor 能看出缺了哪一半。

不装 pandas 那几个库（要联网、要一分钟），只验证"项目的解释器能 import dsflow"这条关键链路。
"""

import subprocess

import pytest

from typer.testing import CliRunner

import dsflow
from dsflow import env as envmod
from dsflow.cli import app as cli
from dsflow.doctor import run_doctor

runner = CliRunner()


def _project(tmp_path, name="环境项目"):
    target = tmp_path / "proj"
    result = runner.invoke(cli, ["init", str(target), "--name", name, "--no-venv"])
    assert result.exit_code == 0, result.output
    return target


def test_init_no_venv_leaves_no_env(tmp_path):
    target = _project(tmp_path)
    assert envmod.venv_python(target) is None
    assert envmod.status(target) == {"venv": False, "python": "", "dsflow_linked": False, "linked_to": [], "libs": []}


def test_prepare_links_dsflow_into_project_python(tmp_path):
    target = _project(tmp_path)
    lines = list(envmod.prepare(target, libs=(), seed=False))
    assert any("已建" in line for line in lines) and any("挂进去" in line for line in lines)
    python = envmod.venv_python(target)
    assert python is not None and python.is_file()
    status = envmod.status(target)
    assert status["venv"] and status["dsflow_linked"]
    assert status["libs"] == []  # 这个测试没装分析库
    # 关键链路：项目自己的解释器能导入 dsflow 和 notebook 执行器（不装第二份 dsflow）
    proc = subprocess.run([str(python), "-c", "import dsflow, dsflow.tracking.notebook; print(dsflow.__version__)"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == dsflow.__version__


def test_prepare_is_idempotent(tmp_path):
    target = _project(tmp_path)
    list(envmod.prepare(target, libs=(), seed=False))
    lines = list(envmod.prepare(target, libs=(), seed=False))
    assert any("直接用" in line for line in lines)
    assert envmod.status(target)["dsflow_linked"]


def test_doctor_reports_missing_and_ready_env(tmp_path):
    target = _project(tmp_path)
    before = {c["name"]: c for c in run_doctor(target)["checks"]}["接入 · 分析环境"]
    assert before["status"] == "fail" and "没有 .venv" in before["detail"]
    assert before["fix"].endswith("attach . --venv")
    list(envmod.prepare(target, libs=(), seed=False))
    after = {c["name"]: c for c in run_doctor(target)["checks"]}["接入 · 分析环境"]
    assert after["status"] == "ok"


def test_doctor_flags_link_pointing_nowhere(tmp_path):
    target = _project(tmp_path)
    list(envmod.prepare(target, libs=(), seed=False))
    packages = envmod.site_packages(target)
    (packages / envmod.PTH_NAME).write_text(str(tmp_path / "搬走了") + "\n", encoding="utf-8")
    check = {c["name"]: c for c in run_doctor(target)["checks"]}["接入 · 分析环境"]
    assert check["status"] == "fail" and "已经不在了" in check["detail"]


def test_attach_venv_prepares_env(tmp_path, monkeypatch):
    target = _project(tmp_path)
    monkeypatch.setattr(envmod, "DEFAULT_LIBS", ())
    result = runner.invoke(cli, ["attach", str(target), "--venv"])
    assert result.exit_code == 0, result.output
    assert "挂进去" in result.output
    assert envmod.status(target)["dsflow_linked"]


@pytest.mark.slow
def test_prepared_env_has_pip(tmp_path):
    """文档告诉用户缺库时可以用 pip 装：uv 建的环境默认没有 pip，要靠 --seed 补上。"""
    target = _project(tmp_path)
    list(envmod.prepare(target, libs=()))
    python = envmod.venv_python(target)
    proc = subprocess.run([str(python), "-m", "pip", "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("pip ")


# ---------- 开工前的环境自检 ----------


def test_quick_check_reports_each_missing_half(tmp_path):
    target = _project(tmp_path)
    before = envmod.quick_check(target)
    assert before["ready"] is False and "没有 .venv" in before["detail"] and before["fix"].endswith("--venv")
    list(envmod.prepare(target, libs=(), seed=False))
    after = envmod.quick_check(target)
    # 挂上了 dsflow；平台自己有 pandas、openpyxl，项目跟着能用，缺的是平台也没有的那几个
    assert after["ready"] is False and "都没有这些库" in after["detail"]
    assert envmod.quick_check(target)["fix"].endswith("--venv")


def test_check_starts_the_project_interpreter(tmp_path):
    target = _project(tmp_path)
    missing = envmod.check(target)
    assert missing["ready"] is False and missing["python"] == ""
    assert missing["checks"][0]["status"] == "fail" and "不存在" in missing["checks"][0]["detail"]

    list(envmod.prepare(target, libs=(), seed=False))
    got = envmod.check(target)
    named = {c["name"]: c for c in got["checks"]}
    # 项目环境挂着平台的 site-packages，所以平台装了的库这里也 import 得到；关键链路是 dsflow 与执行器。
    assert named["import dsflow"]["status"] == "ok" and named["import dsflow.tracking.notebook"]["status"] == "ok"
    assert got["python"].endswith(("python.exe", "python")) and named["分析环境"]["status"] == "ok"


def test_check_accepts_extra_imports(tmp_path):
    target = _project(tmp_path)
    list(envmod.prepare(target, libs=(), seed=False))
    got = envmod.check(target, imports=["json", "谁都没装过的库"])
    named = {c["name"]: c for c in got["checks"]}
    assert named["import json"]["status"] == "ok"                    # 标准库，装了解释器就有
    missing = named["import 谁都没装过的库"]
    assert got["ready"] is False and missing["status"] == "fail"
    assert "ModuleNotFoundError" in missing["detail"] and "pip install 谁都没装过的库" in missing["fix"]
    assert envmod.import_name("scikit-learn") == "sklearn"           # 装的时候写库名，import 的时候写模块名


def test_env_check_tool_and_readonly_env_prepare(tmp_path):
    from dsflow.index.db import PlatformIndex
    from dsflow.protocol import call

    target = _project(tmp_path)
    got = call("env_check", {"project": str(target)})
    assert got["ok"] and got["data"]["ready"] is False and got["data"]["fix"].endswith("--venv")
    row = PlatformIndex().add_project(target, readonly=True)
    denied = call("env_prepare", {"project": row["id"]})
    assert denied["ok"] is False and denied["error"]["code"] == "readonly"
