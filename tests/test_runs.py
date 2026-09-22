"""运行追踪：SDK 记录、dsflow run 挂接同一条记录、失败与中断、复现卡片、日志流、平台重跑、只读禁止重跑。"""

import json
import sys
import textwrap
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import dsflow
from dsflow.cli import app as cli
from dsflow.core.lifecycle import build_graph
from dsflow.core.project import Project
from dsflow.core.validate import parse_registry
from dsflow.data.datasets import DatasetStore
from dsflow.index.db import PlatformIndex
from dsflow.server.app import create_app
from dsflow.tracking.store import RunStore, pid_alive, reproduce

from .conftest import base_registry, write_registry

runner = CliRunner()


@pytest.fixture
def run_project(tmp_path):
    root = tmp_path / "rp"
    write_registry(root, {**base_registry(), "steps": [base_registry()["steps"][1] | {"id": "1.1", "order": 1, "dir": "steps/01_数据预处理/1.1_清洗"}],
                          "dependencies": [], "revision_loops": []})
    (root / "data").mkdir()
    pd.DataFrame({"id": [1, 2, 2, 3], "v": [1.0, 2.0, 2.0, None]}).to_csv(root / "data" / "raw.csv", index=False)
    return root


def write_script(root: Path, body: str) -> Path:
    path = root / "job.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_sdk_records_everything(run_project, monkeypatch):
    monkeypatch.chdir(run_project)
    with dsflow.start_run("1.1", hypothesis="去重后行数减少 1 行") as run:
        run.log_input("data/raw.csv", name="raw")
        run.log_params({"key": "全部字段", "n": pd.Series([3]).iloc[0]})  # numpy 标量也能记
        df = pd.read_csv("data/raw.csv").drop_duplicates()
        run.log_output(df, name="clean", path="steps/01_数据预处理/1.1_清洗/outputs/clean.parquet",
                       description="一行 = 一个清洗后的订单行")
        run.log_metrics({"删除行数": 1})
        run.log_metrics({"mae": 0.5}, fold=1)
        run.log_metrics({"mae": 0.7}, fold=2)
        run.set_conclusion("删除 1 行完全重复行", validity="有效")
    rec = RunStore(Project(run_project, readonly=False)).get(run.run_id)
    assert rec["status"] == "succeeded" and rec["duration_s"] is not None and rec["source"] == "sdk"
    assert rec["params"] == {"key": "全部字段", "n": 3} and rec["metrics"] == {"删除行数": 1.0}
    assert rec["fold_metrics"] == {"1": {"mae": 0.5}, "2": {"mae": 0.7}}
    assert [i["name"] for i in rec["inputs"]] == ["raw"] and rec["outputs"][0]["rows"] == 3
    delta = rec["deltas"][0]
    assert (delta["rows_a"], delta["rows_b"], delta["row_delta"]) == (4, 3, -1)
    chain = {c["name"]: c for c in DatasetStore(Project(run_project, readonly=False)).chain()}
    assert chain["clean"]["produced_by"] == "1.1" and chain["clean"]["parents"] == ["raw"]
    with pytest.raises(ValueError):
        run.set_conclusion("x", validity="大概有效")


def test_sdk_exception_marks_failed(run_project, monkeypatch):
    monkeypatch.chdir(run_project)
    with pytest.raises(RuntimeError):
        with dsflow.start_run("1.1") as run:
            raise RuntimeError("数据坏了")
    rec = RunStore(Project(run_project, readonly=False)).get(run.run_id)
    assert rec["status"] == "failed" and "数据坏了" in rec["error"]


def test_cli_run_attaches_sdk_and_captures_log(run_project):
    write_script(run_project, """
        import dsflow
        print("开始清洗")
        with dsflow.start_run("1.1", hypothesis="写进同一条记录") as run:
            run.log_metrics({"rows": 4})
            run.set_conclusion("完成", validity="有效")
    """)
    result = runner.invoke(cli, ["run", "1.1", "-p", str(run_project), "--hypothesis", "命令行给的假设", "--", sys.executable, "job.py"])
    assert result.exit_code == 0, result.output
    runs = RunStore(Project(run_project, readonly=False)).list()
    assert len(runs) == 1  # SDK 挂到了 dsflow run 创建的那条记录上
    rec = runs[0]
    assert rec["source"] == "cli" and rec["status"] == "succeeded" and rec["exit_code"] == 0
    assert rec["metrics"] == {"rows": 4.0} and rec["hypothesis"] == "命令行给的假设" and rec["conclusion"] == "完成"
    assert "开始清洗" in RunStore(Project(run_project, readonly=False)).log_path(rec["run_id"]).read_text(encoding="utf-8")


def test_cli_run_failure_and_bad_command(run_project):
    write_script(run_project, "import sys\nprint('坏参数')\nsys.exit(3)\n")
    assert runner.invoke(cli, ["run", "1.1", "-p", str(run_project), "--", sys.executable, "job.py"]).exit_code == 1
    assert runner.invoke(cli, ["run", "1.1", "-p", str(run_project), "--", "no-such-program-xyz"]).exit_code == 1
    runs = RunStore(Project(run_project, readonly=False)).list()
    assert {r["status"] for r in runs} == {"failed"}
    assert sorted(r.get("exit_code") for r in runs if r.get("exit_code") is not None) == [3]
    assert any("无法启动命令" in (r.get("error") or "") for r in runs)
    assert runner.invoke(cli, ["run", "1.1", "-p", str(run_project)]).exit_code == 2  # 没给命令


def test_stale_running_run_is_marked_failed(run_project):
    store = RunStore(Project(run_project, readonly=False))
    run = store.create("1.1")
    run["pid"] = 999_999_999
    store.save(run)
    assert not pid_alive(999_999_999)
    assert store.get(run["run_id"])["status"] == "failed" and "没有写入最终结果" in store.get(run["run_id"])["error"]


def test_reproduce_card_is_honest(run_project):
    store = RunStore(Project(run_project, readonly=False))
    run = store.create("1.1", argv=[sys.executable, "job.py"])
    run["inputs"] = [{"name": "raw", "version": "abc", "path": "data/raw.csv", "sha256": "f" * 64}]
    card = reproduce(run)
    assert any(c.startswith("uv run dsflow data verify") for c in card["commands"])
    assert any("dsflow run 1.1" in c for c in card["commands"])
    assert any("不是 git 仓库" in w for w in card["warnings"])  # 临时目录不是 git 仓库，如实说明


def test_data_verify(run_project):
    from dsflow.core.hashing import sha256_file

    sha = sha256_file(run_project / "data" / "raw.csv")
    assert runner.invoke(cli, ["data", "verify", str(run_project), "data/raw.csv", sha]).exit_code == 0
    assert runner.invoke(cli, ["data", "verify", str(run_project), "data/raw.csv", "0" * 64]).exit_code == 1


def test_path_includes_runs(run_project):
    store = RunStore(Project(run_project, readonly=False))
    store.finish(store.create("1.1", hypothesis="h")["run_id"], "succeeded")
    model, _ = parse_registry(json.loads((run_project / "lifecycle" / "steps.json").read_text(encoding="utf-8")))
    path = build_graph(model, run_project, [], store.list())["path"]
    runs = [e for e in path if e["kind"] == "run"]
    assert len(runs) == 1 and runs[0]["status_label"] == "运行成功" and runs[0]["summary"] == "h"


def wait_done(client, url, timeout=60):
    deadline = time.time() + timeout
    while True:
        run = client.get(url).json()
        if run["status"] != "running":
            return run
        assert time.time() < deadline
        time.sleep(0.1)


def test_api_runs_log_stream_and_rerun(run_project):
    write_script(run_project, "print('第一行')\nprint('第二行')\n")
    assert runner.invoke(cli, ["run", "1.1", "-p", str(run_project), "--", sys.executable, "job.py"]).exit_code == 0
    client = TestClient(create_app(PlatformIndex()))
    pid = client.post("/api/projects", json={"path": str(run_project), "readonly": False}).json()["id"]
    runs = client.get(f"/api/projects/{pid}/runs", params={"step": "1.1"}).json()
    rid = runs[0]["run_id"]
    detail = client.get(f"/api/projects/{pid}/runs/{rid}").json()
    assert detail["reproduce"]["commands"] and detail["readonly"] is False and detail["log_size"] > 0
    assert "第二行" in client.get(f"/api/projects/{pid}/runs/{rid}/log").json()["text"]
    with client.stream("GET", f"/api/projects/{pid}/runs/{rid}/stream") as resp:
        body = "".join(resp.iter_text())
    assert "第一行" in body and "event: end" in body and '"succeeded"' in body

    new = client.post(f"/api/projects/{pid}/runs/{rid}/rerun").json()
    assert new["rerun_of"] == rid and new["source"] == "ui"
    done = wait_done(client, f"/api/projects/{pid}/runs/{new['run_id']}")
    assert done["status"] == "succeeded" and "第一行" in client.get(f"/api/projects/{pid}/runs/{new['run_id']}/log").json()["text"]
    assert client.get(f"/api/projects/{pid}/runs/../x").status_code == 404
    assert [e["kind"] for e in client.get(f"/api/projects/{pid}").json()["graph"]["path"]].count("run") == 2


def test_readonly_project_cannot_rerun_from_platform(run_project):
    write_script(run_project, "print('x')\n")
    client = TestClient(create_app(PlatformIndex()))
    pid = client.post("/api/projects", json={"path": str(run_project)}).json()["id"]  # 只读登记
    assert runner.invoke(cli, ["run", "1.1", "-p", str(run_project), "--", sys.executable, "job.py"]).exit_code == 0
    assert not (run_project / ".dsflow").exists()  # 只读项目的运行记录在平台目录
    rid = client.get(f"/api/projects/{pid}/runs").json()[0]["run_id"]
    resp = client.post(f"/api/projects/{pid}/runs/{rid}/rerun")
    assert resp.status_code == 403 and "只读" in resp.json()["detail"]
