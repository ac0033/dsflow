"""答疑：上下文、只读工具边界、数字核对、存档，以及网页那条 SSE 路由。

不连真实模型：用一个假后端按脚本吐 Turn，把流程跑通。
"""

import json

import pytest
from fastapi.testclient import TestClient

from dsflow.ask import tools as ask_tools
from dsflow.ask.context import Scope, build
from dsflow.ask.session import answer, status
from dsflow.ask.store import AskStore, Record
from dsflow.chat.config import ModelEntry
from dsflow.chat.llm import Backend, ToolCall, Turn
from dsflow.core.project import Project
from dsflow.index.db import PlatformIndex
from dsflow.protocol import REGISTRY
from dsflow.server.app import create_app

STEP_11 = "steps/01_数据预处理/1.1_盘点"
REV_11 = f"{STEP_11}/revisions/r02_2026-09-15_修正"


class FakeBackend(Backend):
    """按脚本回答：turns 是一串 Turn，一次调用吐一个。"""

    def __init__(self, turns: list[Turn]):
        super().__init__(None)
        self.turns = list(turns)
        self.seen: list[list[dict]] = []

    def complete(self, system: str, transcript: list[dict], tools: list[dict]) -> Turn:
        self.seen.append([dict(m) for m in transcript])
        self.system = system
        self.tools = tools
        return self.turns.pop(0) if self.turns else Turn(text="")


def open_project(root) -> Project:
    index = PlatformIndex()
    row = index.add_project(str(root), readonly=True)
    return index.open_project(row["id"])


# ---------- 只读边界 ----------


def test_readonly_list_only_names_existing_read_tools():
    assert set(ask_tools.READONLY) <= set(REGISTRY)
    forbidden = {"file_write", "run_exec", "step_set_status", "approval_decide", "guide_put", "data_register",
                 "vocabulary_add", "step_add", "model_register", "decisions_add"}
    assert not (set(ask_tools.READONLY) & forbidden)
    assert [s["name"] for s in ask_tools.specs()] == list(ask_tools.READONLY)


def test_write_tool_is_refused_and_nothing_is_written(mini_project):
    root, _ = mini_project
    project = open_project(root)
    reg, _ = project.load()
    backend = FakeBackend([
        Turn(text="", tool_calls=[ToolCall("t1", "file_write", {"path": f"{STEP_11}/plan.md", "content": "被改掉了"})], stop="tool"),
        Turn(text="这一步的计划文件我只能读，不能改。"),
    ])
    events = list(answer(project, reg, Scope(step="1.1", tab="plan"), "帮我把计划改一下", backend=backend))
    results = [e for e in events if e["type"] == "result"]
    assert results and results[0]["ok"] is False and "只读" in results[0]["message"]
    assert (root / STEP_11 / "plan.md").read_text(encoding="utf-8") == "# 1.1 计划\n"


def test_answer_links_point_at_files_that_really_exist(mini_project):
    """答案里提到的文件与单元格，要能点着跳过去；项目里没有的一律不给链接。"""
    from dsflow.ask.links import find_links

    root, _ = mini_project
    project = open_project(root)
    reg, _ = project.load()
    answer = (f"单元格 3 把计划写进了 {STEP_11}/plan.md，"
              "另外 data/不存在的表.csv 这张表我没有找到。")
    links = find_links(project, reg, answer, "1.1")
    kinds = {l["label"]: l for l in links}
    assert "plan.md" in kinds and kinds["plan.md"]["kind"] == "file" and kinds["plan.md"]["step"] == "1.1"
    assert "单元格 3" in kinds and kinds["单元格 3"]["cell"] == 3
    assert "不存在的表.csv" not in kinds, "项目里没有的文件不给链接，跳错地方比不跳更糟"


# ---------- 上下文 ----------


def test_context_carries_position_quote_and_terms(mini_project):
    root, _ = mini_project
    project = open_project(root)
    reg, _ = project.load()
    ctx = build(project, reg, Scope(step="1.1", rev="r02", tab="plan", file=f"{REV_11}/plan.md", quote="r02 计划"))
    assert "1.1 盘点" in ctx.text and "执行计划" in ctx.text
    assert "r02 计划" in ctx.text and "r02 计划" in ctx.sources
    assert "字段含义已经逐个确认清楚。" in ctx.sources  # 讲解开头也算出处，数字核对要用
    assert ctx.file.endswith("plan.md")


def test_context_lists_every_marked_spot_with_its_note(mini_project):
    """先标几处再一起问：每一处的原文和用户写的备注都进上下文，也都算数字核对的出处。"""
    root, _ = mini_project
    project = open_project(root)
    reg, _ = project.load()
    notes = [{"quote": "r02 计划", "note": "这句看不懂"}, {"quote": "字段含义", "note": ""}]
    ctx = build(project, reg, Scope(step="1.1", rev="r02", tab="plan", file=f"{REV_11}/plan.md", notes=notes))
    assert "先标注了 2 处" in ctx.text
    assert "1. 原文「r02 计划」；他在这一处写的备注是：这句看不懂" in ctx.text
    assert "2. 原文「字段含义」；他在这一处没有写备注。" in ctx.text
    assert "r02 计划" in ctx.sources and "字段含义" in ctx.sources


def test_scope_trims_notes_and_falls_back_to_the_first_one(mini_project):
    """标注按登记的字段收进来：空原文丢掉、条数有上限，没选中单句时原文片段以第一处标注为中心切。"""
    scope = Scope.from_dict({"step": "1.1", "notes": [{"quote": " 头一处 ", "note": " 备注 "}, {"quote": "  "}]})
    assert scope.notes == [{"quote": "头一处", "note": "备注"}]
    assert scope.anchor == "头一处"
    assert Scope.from_dict({"quote": "选中的那句", "notes": [{"quote": "头一处"}]}).anchor == "选中的那句"
    # 标注过的一定钉在页面上；只选中一句时要用户自己勾「标注」
    assert Scope.from_dict({"notes": [{"quote": "头一处"}]}).pinned is True
    assert Scope.from_dict({"quote": "一句话"}).pinned is False
    assert Scope.from_dict({"quote": "一句话", "mark": True}).pinned is True
    many = Scope.from_dict({"notes": [{"quote": f"第 {i} 处"} for i in range(30)]})
    assert len(many.notes) == 12


def test_context_without_step_still_names_the_project(mini_project):
    root, _ = mini_project
    project = open_project(root)
    reg, _ = project.load()
    ctx = build(project, reg, Scope(tab="board"))
    assert project.name in ctx.text and "看板" in ctx.text


# ---------- 一轮问答 ----------


def test_answer_streams_text_checks_numbers_and_saves(mini_project):
    root, _ = mini_project
    project = open_project(root)
    reg, _ = project.load()
    backend = FakeBackend([
        Turn(text="", tool_calls=[ToolCall("t1", "steps_list", {})], stop="tool"),
        Turn(text="这个项目有 3 个步骤。抽样比例是 37.5%。"),
    ])
    events = list(answer(project, reg, Scope(step="1.1", tab="guide", quote="字段含义"), "这一步在做什么？", backend=backend, model_name="假模型"))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "tool" and "text" in kinds and kinds[-1] == "done"
    record = events[-1]["record"]
    assert record["tools"] == ["steps_list"] and record["model"] == "假模型"
    # 3 来自工具返回（找得到出处），37.5% 是模型自己编的（找不到）
    assert record["unverified"] == ["37.5%"]

    stored = AskStore(project).list("1.1")
    assert len(stored) == 1 and stored[0].question == "这一步在做什么？" and stored[0].quote == "字段含义"


def test_answer_keeps_every_marked_spot_in_the_record(mini_project):
    """一次问多处：几处标注连同备注一起存进这条问答，界面按它把几句话都钉回页面。"""
    root, _ = mini_project
    project = open_project(root)
    reg, _ = project.load()
    notes = [{"quote": "字段含义", "note": "这里指什么"}, {"quote": "r02 计划", "note": ""}]
    backend = FakeBackend([Turn(text="第 1 处说的是列的意思。第 2 处说的是这一轮要做的事。")])
    events = list(answer(project, reg, Scope(step="1.1", tab="guide", notes=notes), "这两处分别在说什么？", backend=backend))
    record = events[-1]["record"]
    assert record["notes"] == notes and record["quote"] == ""
    stored = AskStore(project).list("1.1")[0]
    # 钉住写在存档那一刻：答到一半用户关掉页面，这几句照样钉得住
    assert stored.notes == notes and stored.mark is True


def test_answer_reports_model_errors_instead_of_crashing(mini_project):
    root, _ = mini_project
    project = open_project(root)
    reg, _ = project.load()

    class Broken(Backend):
        def complete(self, system, transcript, tools):
            from dsflow.chat.llm import LLMError

            raise LLMError("密钥无效：test")

    events = list(answer(project, reg, Scope(step="1.1"), "在做什么？", backend=Broken()))
    assert events[-1]["type"] == "error" and "密钥无效" in events[-1]["message"]
    assert AskStore(project).list("1.1")[0].error.startswith("密钥无效")


# ---------- 存档 ----------


def test_store_marks_and_deletes(mini_project):
    root, _ = mini_project
    project = open_project(root)
    store = AskStore(project)
    record = store.add(Record(id="q1", at=1.0, question="QC 是什么？", answer="质量核对。", step="1.1", quote="QC"))
    assert store.list("1.1")[0].mark is False
    assert store.update("q1", "1.1", mark=True).mark is True
    assert store.list("1.1")[0].mark is True
    assert store.delete("q1", "1.1") is True and store.list("1.1") == []
    assert store.delete(record.id, "1.1") is False


def test_store_stays_out_of_a_readonly_project(mini_project):
    root, _ = mini_project
    project = open_project(root)
    AskStore(project).add(Record(id="q1", at=1.0, question="问", step="1.1"))
    assert not (root / ".dsflow").exists()
    assert (project.state_dir() / "asks" / "1.1.jsonl").is_file()


# ---------- 网页路由 ----------


def test_status_without_a_model_tells_the_user_what_to_do():
    got = status()
    assert got["ready"] is False and "保存并连接" in got["hint"]


def test_routes_ask_list_mark_and_terms(mini_project, monkeypatch):
    root, _ = mini_project
    index = PlatformIndex()
    client = TestClient(create_app(index, mcp=False))
    pid = client.post("/api/projects", json={"path": str(root)}).json()["id"]

    entry = ModelEntry(name="假模型", provider="anthropic", model="claude-opus-5")
    monkeypatch.setattr("dsflow.ask.session.active_model", lambda: entry)
    monkeypatch.setattr("dsflow.ask.session.make_backend", lambda entry: FakeBackend([Turn(text="QC 是数据质量核对。")]))

    with client.stream("POST", f"/api/projects/{pid}/ask",
                       json={"question": "QC 是什么？", "step": "1.1", "tab": "plan", "quote": "QC", "mark": True, "tools": False}) as resp:
        assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ")]
    assert [e["type"] for e in events][-1] == "done"
    record = events[-1]["record"]
    assert record["answer"].startswith("QC") and record["mark"] is True

    listed = client.get(f"/api/projects/{pid}/asks", params={"step": "1.1"}).json()["records"]
    assert len(listed) == 1 and listed[0]["id"] == record["id"]

    off = client.patch(f"/api/projects/{pid}/asks/{record['id']}", json={"mark": False, "step": "1.1"})
    assert off.status_code == 200 and off.json()["mark"] is False

    saved = client.post(f"/api/projects/{pid}/asks/{record['id']}/term",
                        json={"term": "QC", "meaning": "数据质量核对。", "step": "1.1"})
    assert saved.status_code == 200
    terms = client.get(f"/api/projects/{pid}/terms", params={"step": "1.1"}).json()["terms"]
    assert any(t["term"] == "QC" and t["plain"] == "数据质量核对。" for t in terms)

    assert client.delete(f"/api/projects/{pid}/asks/{record['id']}", params={"step": "1.1"}).json()["deleted"] is True
    assert client.get(f"/api/projects/{pid}/asks", params={"step": "1.1"}).json()["records"] == []


def test_ask_route_pins_the_marked_spots_without_asking_for_mark(mini_project, monkeypatch):
    """带标注发过来的问答自动钉在页面上：不用再勾一次「标注」，几处原文都留着。"""
    root, _ = mini_project
    index = PlatformIndex()
    client = TestClient(create_app(index, mcp=False))
    pid = client.post("/api/projects", json={"path": str(root)}).json()["id"]

    entry = ModelEntry(name="假模型", provider="anthropic", model="claude-opus-5")
    monkeypatch.setattr("dsflow.ask.session.active_model", lambda: entry)
    monkeypatch.setattr("dsflow.ask.session.make_backend", lambda entry: FakeBackend([Turn(text="两处说的是同一件事。")]))

    body = {"question": "这两处分别在说什么？", "step": "1.1", "tab": "plan", "tools": False,
            "notes": [{"quote": "QC", "note": "缩写没见过"}, {"quote": "r02 计划", "note": ""}]}
    with client.stream("POST", f"/api/projects/{pid}/ask", json=body) as resp:
        events = [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ")]
    record = events[-1]["record"]
    assert record["mark"] is True and [n["quote"] for n in record["notes"]] == ["QC", "r02 计划"]
    listed = client.get(f"/api/projects/{pid}/asks", params={"step": "1.1"}).json()["records"]
    assert listed[0]["mark"] is True and listed[0]["notes"][0]["note"] == "缩写没见过"


def test_ask_route_without_a_model_answers_with_one_error_event(mini_project):
    root, _ = mini_project
    index = PlatformIndex()
    client = TestClient(create_app(index, mcp=False))
    pid = client.post("/api/projects", json={"path": str(root)}).json()["id"]
    with client.stream("POST", f"/api/projects/{pid}/ask", json={"question": "这是什么？"}) as resp:
        events = [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ")]
    assert len(events) == 1 and events[0]["type"] == "error" and "保存并连接" in events[0]["message"]


def test_terms_route_gives_builtin_terms_without_a_step(mini_project):
    root, _ = mini_project
    index = PlatformIndex()
    client = TestClient(create_app(index, mcp=False))
    pid = client.post("/api/projects", json={"path": str(root)}).json()["id"]
    terms = client.get(f"/api/projects/{pid}/terms").json()["terms"]
    assert terms and all(t["plain"] for t in terms)


@pytest.mark.parametrize("name", ["data_peek"])
def test_new_readonly_tool_is_in_the_protocol(name):
    assert name in REGISTRY and REGISTRY[name].group == "数据"


# ---------- 在网页上配模型 ----------


def local_client() -> TestClient:
    """TestClient 默认的来源不是本机地址，模型配置接口会挡下来；这里明确成 127.0.0.1。"""
    return TestClient(create_app(PlatformIndex(), mcp=False), client=("127.0.0.1", 5555))


def test_model_config_saves_tests_switches_and_deletes(monkeypatch):
    client = local_client()
    listing = client.get("/api/ask/models").json()
    assert listing["models"] == [] and any(p["preset"] == "deepseek" and p["where"] for p in listing["presets"])
    assert listing["path"].endswith("models.json")

    added = client.post("/api/ask/models", json={"preset": "deepseek", "api_key": "sk-abcdef123456"})
    assert added.status_code == 200
    row = added.json()
    assert row["active"] is True and row["ready"] is True and row["model"] == "deepseek-chat"
    assert "sk-abcdef123456" not in json.dumps(row, ensure_ascii=False)  # 密钥不原样回给页面
    assert client.get("/api/ask/status").json()["ready"] is True

    monkeypatch.setattr("dsflow.ask.models.make_backend", lambda entry: FakeBackend([Turn(text="可以。")]))
    tested = client.post("/api/ask/models/test").json()
    assert tested["ok"] is True and tested["message"] == "可以。"

    second = client.post("/api/ask/models", json={"preset": "openai", "api_key": "sk-openai-123456", "model": "gpt-5-mini"}).json()
    assert second["active"] is True and second["model"] == "gpt-5-mini"
    back = client.post(f"/api/ask/models/{row['name']}/use").json()
    assert back["active"] is True and back["name"] == row["name"]

    assert client.delete(f"/api/ask/models/{second['name']}").json()["removed"] == second["name"]
    assert [m["name"] for m in client.get("/api/ask/models").json()["models"]] == [row["name"]]


def test_model_needing_a_key_says_so_instead_of_saving_a_dead_entry():
    client = local_client()
    resp = client.post("/api/ask/models", json={"preset": "moonshot"})
    assert resp.status_code == 400 and "密钥" in resp.json()["detail"]
    assert client.get("/api/ask/models").json()["models"] == []


def test_ollama_needs_no_key():
    client = local_client()
    row = client.post("/api/ask/models", json={"preset": "ollama"}).json()
    assert row["ready"] is True and row["base_url"].startswith("http://127.0.0.1:11434")


def test_model_config_refuses_requests_from_another_machine():
    outside = TestClient(create_app(PlatformIndex(), mcp=False), client=("10.0.0.9", 5555))
    assert outside.get("/api/ask/models").status_code == 403
    assert outside.post("/api/ask/models", json={"preset": "deepseek", "api_key": "sk-x"}).status_code == 403
    assert outside.get("/api/ask/status").status_code == 200  # 只看状态不涉及密钥，仍然可以
