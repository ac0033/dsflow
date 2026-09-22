"""DSFlow Agent Protocol：登记表、信封、三种传输的一致性、文件写入护栏、状态护栏、运行、术语、待决、审批长轮询。"""

import copy
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dsflow import protocol
from dsflow.cli import app as cli
from dsflow.core.project import Project
from dsflow.index.db import PlatformIndex
from dsflow.paths import REPO_ROOT
from dsflow.protocol import REGISTRY, call, protocol_document, protocol_markdown
from dsflow.server.app import create_app

from .conftest import REV_11, S1, STEP_11, write_registry

runner = CliRunner()
STEP_12 = f"{S1}/1.2_清洗"


def touch(root, rel, text="x\n"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def set_status(root, reg, step_id, status):
    reg = copy.deepcopy(reg)
    next(s for s in reg["steps"] if s["id"] == step_id)["status"] = status
    write_registry(root, reg)
    return reg


def data(env):
    assert env["ok"], env
    return env["data"]


# ---------- 登记表与信封 ----------

def test_registry_and_document_are_consistent():
    doc = protocol_document()
    assert doc["protocol"] == "1" and {t["name"] for t in doc["tools"]} == set(REGISTRY)
    for spec in REGISTRY.values():
        schema = spec.schema()
        assert "project" in schema["properties"] or spec.name in ("protocol_get", "projects_list")
        for pname in schema["properties"]:
            assert pname in spec.params or pname == "project", f"{spec.name}.{pname} 没有说明"
    md = protocol_markdown()
    assert all(f"`{name}`" in md for name in REGISTRY)
    assert {(a, b) for a, b in protocol.AGENT_TRANSITIONS} == {("pending", "pending_approval"), ("in_progress", "awaiting_acceptance")}


def test_envelope_for_unknown_tool_and_bad_args(mini_project):
    root, _ = mini_project
    assert call("nope")["error"]["code"] == "not_found"
    bad = call("next", {"project": str(root), "bogus": 1})
    assert bad["ok"] is False and bad["error"]["code"] == "invalid" and "bogus" in bad["error"]["message"]
    assert call("file_read", {})["error"]["code"] == "invalid"
    assert call("file_read", {"project": str(root), "path": "nope.md"})["error"]["code"] == "not_found"
    assert call("next", {"project": "0123456789"})["error"]["code"] == "not_found"


def test_project_accepts_id_or_path(mini_project):
    root, _ = mini_project
    row = PlatformIndex().add_project(root, readonly=False)
    by_id = data(call("next", {"project": row["id"]}))
    by_path = data(call("next", {"project": str(root)}))
    assert by_id["step"]["id"] == by_path["step"]["id"] == "1.2" and by_id["protocol"] == "1"
    # 测试项目没有建 .venv，所以第一件事是环境自检，写计划排在它后面
    assert by_id["environment"]["ready"] is False
    assert [c["tool"] for c in by_id["tool_calls"]][:3] == ["env_check", "env_prepare", "file_write"]
    assert all(c["args"]["project"] == row["id"] for c in by_id["tool_calls"])
    assert [p["id"] for p in data(call("projects_list"))] == [row["id"]]


# ---------- 三种传输 ----------

def test_cli_and_http_transports_share_the_registry(mini_project):
    root, _ = mini_project
    result = runner.invoke(cli, ["call", "steps_list", "-p", str(root)])
    assert result.exit_code == 0
    env = json.loads(result.output)
    assert env["ok"] and [s["id"] for s in env["data"]] == ["1.1", "1.2", "2.1"]
    assert runner.invoke(cli, ["call", "nope"]).exit_code == 1
    assert runner.invoke(cli, ["call", "next", "--args", "{bad"]).exit_code == 1
    listing = runner.invoke(cli, ["protocol"])
    assert listing.exit_code == 0 and "个工具" in listing.output
    as_json = json.loads(runner.invoke(cli, ["protocol", "--format", "json"]).output)
    assert {t["name"] for t in as_json["tools"]} == set(REGISTRY)

    client = TestClient(create_app(PlatformIndex()))
    assert {t["name"] for t in client.get("/api/protocol").json()["tools"]} == set(REGISTRY)
    r = client.post("/api/tools/steps_list", json={"project": str(root)})
    assert r.status_code == 200 and r.json()["ok"] and len(r.json()["data"]) == 3
    r = client.post("/api/tools/nope", json={})
    assert r.status_code == 200 and r.json()["error"]["code"] == "not_found"


def test_mcp_server_exposes_every_tool():
    pytest.importorskip("mcp.server.mcpserver")
    import asyncio

    from dsflow.mcp_server import build_server

    names = {t.name for t in asyncio.run(build_server().list_tools())}
    assert names == set(REGISTRY)


# ---------- 文件与状态护栏 ----------

def test_file_write_guards(mini_project):
    root, reg = mini_project
    d = str(root)
    out = data(call("file_write", {"project": d, "path": f"{STEP_12}/plan.md", "content": "# 1.2 计划\n"}))
    assert out["path"] == f"{STEP_12}/plan.md" and (root / STEP_12 / "plan.md").read_text(encoding="utf-8") == "# 1.2 计划\n"
    data(call("file_write", {"project": d, "path": f"{STEP_12}/plan.md", "content": "追加\n", "append": True}))
    assert (root / STEP_12 / "plan.md").read_text(encoding="utf-8").endswith("追加\n")
    data(call("file_write", {"project": d, "path": "src/lib.py", "content": "x = 1\n"}))
    for path in ("data/raw/a.csv", "lifecycle/steps.json", f"{STEP_12}/approval_record.md", "dsflow.yaml", ".dsflow/x.json"):
        assert call("file_write", {"project": d, "path": path, "content": "x"})["error"]["code"] == "forbidden", path
    # 1.1 的当前轮次是 r02：r01 目录（步骤目录本身）算历史，不能写
    assert call("file_write", {"project": d, "path": f"{STEP_11}/report.md", "content": "x"})["error"]["code"] == "forbidden"
    data(call("file_write", {"project": d, "path": f"{REV_11}/report.md", "content": "# 1.1 报告\n"}))
    assert call("file_write", {"project": d, "path": "../outside.md", "content": "x"})["error"]["code"] == "forbidden"
    assert call("file_write", {"project": d, "path": "notes.md", "content": "x"})["error"]["code"] == "forbidden"
    bad = data(call("file_write", {"project": d, "path": f"{REV_11}/guide.yaml", "content": 'step: "1.1"\nbrief:\n  question: 对不对\n  answer: 先对上\n'}))
    assert bad["lint"] and any("对上" in i for x in bad["lint"] for i in x["issues"])
    ro = Project(root, readonly=True)
    PlatformIndex().add_project(root, readonly=True)
    assert call("file_write", {"project": ro.id, "path": f"{STEP_12}/plan.md", "content": "x"})["error"]["code"] == "readonly"


def test_step_set_status_only_agent_transitions(mini_project):
    root, reg = mini_project
    d = str(root)
    out = data(call("step_set_status", {"project": d, "step": "1.2", "status": "pending_approval"}))
    assert (out["from"], out["to"]) == ("pending", "pending_approval")
    conflict = call("step_set_status", {"project": d, "step": "1.2", "status": "done"})
    assert conflict["error"]["code"] == "conflict" and "agent 只能做" in conflict["error"]["hint"]
    assert call("step_set_status", {"project": d, "step": "1.2", "status": "in_progress"})["error"]["code"] == "conflict"
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "in_progress")
    out = data(call("step_set_status", {"project": d, "step": "1.2", "status": "awaiting_acceptance"}))
    assert out["to"] == "awaiting_acceptance"
    nxt = data(call("next", {"project": d}))
    assert nxt["phase"] == "acceptance" and nxt["tool_calls"][-1]["tool"] == "approval_wait"


# ---------- 运行 ----------

def test_run_exec_script_and_run_get(mini_project):
    root, reg = mini_project
    d = str(root)
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    touch(root, f"{STEP_12}/src/hello.py", "print('你好，运行')\n")
    set_status(root, reg, "1.2", "in_progress")
    out = data(call("run_exec", {"project": d, "step": "1.2", "target": f"{STEP_12}/src/hello.py", "hypothesis": "能跑", "timeout": 120}))
    assert out["status"] == "succeeded" and out["exit_code"] == 0 and "你好，运行" in out["log_tail"]
    again = data(call("run_get", {"project": d, "run_id": out["run_id"]}))
    assert again["status"] == "succeeded"
    runs = data(call("runs_list", {"project": d, "step": "1.2"}))
    assert runs[0]["run_id"] == out["run_id"] and runs[0]["hypothesis"] == "能跑"
    assert call("run_exec", {"project": d, "step": "1.2", "target": "data/raw/x.py"})["error"]["code"] == "not_found"
    touch(root, f"{STEP_12}/notes.txt", "x")
    assert call("run_exec", {"project": d, "step": "1.2", "target": f"{STEP_12}/notes.txt"})["error"]["code"] == "invalid"
    assert call("run_get", {"project": d, "run_id": "nope"})["error"]["code"] == "not_found"


# ---------- 数据、术语、待决 ----------

def test_data_vocabulary_decisions(mini_project):
    root, _ = mini_project
    d = str(root)
    touch(root, "data/raw/orders.csv", "id,v\n1,2\n")
    out = data(call("data_register", {"project": d, "path": "data/raw/orders.csv", "name": "orders_raw", "stage": "raw",
                                      "description": "一行 = 一个原始订单行"}))
    assert out["created"] and out["version"]["version"]
    assert data(call("data_link", {"project": d, "name": "orders_raw", "step": "1.1", "role": "核对"}))["role"] == "核对"
    touch(root, f"{REV_11}/outputs/orders_clean.csv", "id,v\n1,2\n")
    data(call("data_register", {"project": d, "path": f"{REV_11}/outputs/orders_clean.csv", "name": "orders_clean", "stage": "processed",
                                "parents": ["orders_raw"], "produced_by": "1.1", "replaces": ["orders_raw"],
                                "description": "一行 = 一个清洗后的订单行"}))
    names = {x["name"] for x in data(call("data_list", {"project": d}))}
    assert names == {"orders_raw", "orders_clean"}
    assert data(call("data_replace", {"project": d, "name": "orders_clean", "old": ["orders_raw"]}))["replaces"] == ["orders_raw"]

    assert data(call("vocabulary_get", {"project": d})) == []
    out = data(call("vocabulary_add", {"project": d, "term": "采购单", "meaning": "一行一个采购行", "source": "表名", "avoid": ["订单"]}))
    assert out["path"] == "vocabulary.json"
    data(call("vocabulary_add", {"project": d, "term": "采购单", "meaning": "更新后的解释"}))
    vocab = data(call("vocabulary_get", {"project": d}))
    assert len(vocab) == 1 and vocab[0]["meaning"] == "更新后的解释" and vocab[0]["avoid"] == ["订单"]

    item = data(call("decisions_add", {"project": d, "question": "按下单还是支付时间？", "recommendation": "下单", "blocking": True, "step": "1.2"}))
    assert item["id"] == "P1" and item["status"] == "unresolved"
    assert [x["question"] for x in data(call("decisions_list", {"project": d}))] == ["按下单还是支付时间？"]


# ---------- 讲解与核对 ----------

def test_guide_tools_and_checks(mini_project):
    root, _ = mini_project
    d = str(root)
    got = data(call("guide_get", {"project": d, "step": "1.1"}))
    assert got["guide"]["brief"]["answer"].startswith("字段含义")
    init = data(call("guide_init", {"project": d, "step": "1.1"}))
    assert init["existed"] is True and init["path"] == f"{REV_11}/guide.yaml"
    chk = data(call("guide_check", {"project": d, "step": "1.1"}))
    assert "checked" in chk
    put = data(call("guide_put", {"project": d, "step": "1.1", "text": 'step: "1.1"\nbrief:\n  question: 对不对\n  answer: 先对上\n', "rev": "r02"}))
    assert put["lint"] and put["path"] == f"{REV_11}/guide.yaml"
    assert call("guide_put", {"project": d, "step": "1.1", "text": "brief: [", "rev": "r02"})["error"]["code"] == "invalid"
    assert call("guide_check", {"project": d, "step": "1.2"})["error"]["code"] == "not_found"
    assert data(call("validate", {"project": d}))["ok"] is True
    assert "alerts" in data(call("check", {"project": d, "step": "1.1"}))


# ---------- 审批 ----------

def test_approval_tools_long_poll(mini_project):
    root, reg = mini_project
    d = str(root)
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "pending_approval")
    assert data(call("approval_get", {"project": d, "step": "1.2"}))["pending"] == "approval"
    t0 = time.monotonic()
    assert data(call("approval_wait", {"project": d, "step": "1.2", "timeout": 1}))["result"] == "pending"
    assert time.monotonic() - t0 < 5

    def later():
        time.sleep(0.5)
        call("approval_decide", {"project": d, "step": "1.2", "decision": "approve", "note": "对话里同意了。"})

    threading.Thread(target=later).start()
    got = data(call("approval_wait", {"project": d, "step": "1.2", "timeout": 10}))
    assert got["result"] == "approved" and got["entry"]["source"] == "MCP"
    assert data(call("next", {"project": d}))["phase"] == "execute"


def test_done_accepts_skill_report_names(mini_project):
    root, reg = mini_project
    reg = copy.deepcopy(reg)
    reg["steps"][1]["status"] = "done"
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    touch(root, f"{STEP_12}/user-report.md", "# 1.2 用户报告\n")
    touch(root, f"{STEP_12}/nb_1.2.ipynb", "{}")
    write_registry(root, reg)
    issues = data(call("validate", {"project": str(root)}))["issues"]
    assert not any(i["code"] == "missing_file" for i in issues)


def test_protocol_doc_in_repo_matches_registry():
    doc = (REPO_ROOT / "docs" / "agent-protocol.md").read_text(encoding="utf-8")
    assert protocol_markdown() in doc
