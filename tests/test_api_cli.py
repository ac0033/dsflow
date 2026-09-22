import json

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dsflow.cli import app as cli
from dsflow.core.project import Project
from dsflow.index.db import PlatformIndex
from dsflow.paths import REPO_ROOT
from dsflow.server.app import create_app

runner = CliRunner()


def test_api_register_read_and_unregister(mini_project):
    root, _ = mini_project
    client = TestClient(create_app(PlatformIndex()))

    resp = client.post("/api/projects", json={"path": str(root)})
    assert resp.status_code == 201
    row = resp.json()
    assert row["readonly"] is True and row["step_count"] == 3 and row["error_count"] == 0

    detail = client.get(f"/api/projects/{row['id']}").json()
    assert detail["issues"] == []
    assert [n["id"] for n in detail["graph"]["nodes"]] == ["1.1", "1.2", "2.1"]
    assert client.get("/api/projects").json()[0]["status_counts"] == {"done": 1, "pending": 2}

    report = client.get(f"/api/projects/{row['id']}/file", params={"path": "steps/01_数据预处理/1.1_盘点/report.md"})
    assert report.status_code == 200 and report.json()["content"].startswith("# 1.1")
    assert client.get(f"/api/projects/{row['id']}/file", params={"path": "../outside.md"}).status_code == 400
    assert client.get(f"/api/projects/{row['id']}/file", params={"path": "missing.md"}).status_code == 404

    assert client.delete(f"/api/projects/{row['id']}").json() == {"removed": True}
    assert root.joinpath("lifecycle/steps.json").is_file()  # 注销不删文件
    assert client.get(f"/api/projects/{row['id']}").status_code == 404


def test_api_rejects_directory_without_registry(tmp_path):
    client = TestClient(create_app(PlatformIndex()))
    resp = client.post("/api/projects", json={"path": str(tmp_path)})
    assert resp.status_code == 400 and "注册表" in resp.json()["detail"]


def test_readonly_project_state_stays_outside(mini_project, isolated_home):
    root, _ = mini_project
    project = Project(root, readonly=True)
    assert project.state_dir().is_relative_to(isolated_home)
    assert Project(root, readonly=False).state_dir() == root / ".dsflow"


def test_cli_init_validate_import(tmp_path):
    target = tmp_path / "new"
    assert runner.invoke(cli, ["init", str(target), "--name", "新项目", "--no-venv"]).exit_code == 0
    assert json.loads((target / "lifecycle/steps.json").read_text(encoding="utf-8"))["title"] == "新项目"
    assert runner.invoke(cli, ["init", str(target), "--name", "再来", "--no-venv"]).exit_code == 1

    result = runner.invoke(cli, ["validate", str(target)])
    assert result.exit_code == 0 and "校验通过" in result.output

    result = runner.invoke(cli, ["import", str(target)])
    assert result.exit_code == 0 and "只读" in result.output
    assert "新项目" in runner.invoke(cli, ["projects"]).output


def test_cli_validate_reports_failure(mini_project):
    root, reg = mini_project
    reg["dependencies"][0]["to"] = "1.999"
    (root / "lifecycle/steps.json").write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    result = runner.invoke(cli, ["validate", str(root)])
    assert result.exit_code == 1 and "1.999" in result.output


def test_demo_project_is_valid():
    result = runner.invoke(cli, ["validate", str(REPO_ROOT / "examples" / "demo_project")])
    assert result.exit_code == 0, result.output


def test_schema_export(tmp_path):
    result = runner.invoke(cli, ["schema", "--out", str(tmp_path)])
    assert result.exit_code == 0
    card = json.loads((tmp_path / "step_card.schema.json").read_text(encoding="utf-8"))
    assert "headline" in card["required"]
