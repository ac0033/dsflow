"""dsflow 命令行入口。"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import typer

from .core.project import Project, ProjectError
from .core.schemas import CONTRACTS
from .index.db import PlatformIndex
from .paths import REPO_ROOT, cli_prefix, templates_dir, web_dist

app = typer.Typer(help="DSFlow：数据科学项目全周期追踪平台", no_args_is_help=True, add_completion=False)


@app.callback(invoke_without_command=True)
def _main(
    version: bool = typer.Option(False, "--version", "-V", help="打印版本号后退出"),
) -> None:
    # Windows 下管道进来的中文默认按本机代码页读，会变成代理字符并在写文件时崩；三个流统一按 UTF-8
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if version:
        from . import __version__

        typer.echo(f"dsflow {__version__}（装得全不全用 {cli_prefix()} doctor 看）")
        raise typer.Exit(0)


@app.command()
def init(
    path: Path,
    name: str = typer.Option(..., "--name", help="项目名称"),
    do_attach: bool = typer.Option(True, "--attach/--no-attach", help="建完就接入：装 CLAUDE.md、skill、hook 并登记为可写"),
    venv: bool = typer.Option(True, "--venv/--no-venv", help="建完就准备分析环境：项目里的 .venv、基础分析库、挂上 dsflow（第一次要联网下载，约一到几分钟）"),
) -> None:
    """用模板在 PATH 新建一个 DSFlow 项目，接入平台，并准备好 agent 执行代码用的分析环境。"""
    from .attach import PLACEHOLDER, attach

    target = path.resolve()
    if (target / "dsflow.yaml").exists() or (target / "lifecycle" / "steps.json").exists():
        typer.echo(f"{target} 已经是一个项目，未做任何改动。")
        raise typer.Exit(1)
    shutil.copytree(templates_dir() / "project", target, dirs_exist_ok=True)
    for rel in ("dsflow.yaml", "lifecycle/steps.json"):
        file = target / rel
        file.write_text(file.read_text(encoding="utf-8").replace("__NAME__", name), encoding="utf-8")
    typer.echo(f"已创建项目「{name}」：{target}")
    if not do_attach:
        for file in target.rglob("*.md"):
            file.write_text(file.read_text(encoding="utf-8").replace(PLACEHOLDER, "dsflow"), encoding="utf-8")
    else:
        try:
            for line in attach(target, force=True):
                typer.echo(f"  {line}")
        except ProjectError as exc:
            _fail(exc)
    if venv:
        _prepare_env(target)


@app.command("attach")
def attach_cmd(
    path: Path = typer.Argument(Path("."), help="项目目录（要已经有 dsflow.yaml）"),
    python: Path | None = typer.Option(None, "--python", help="hook 用哪个解释器（默认当前这个）"),
    force: bool = typer.Option(False, "--force", help="覆盖已有的 AGENTS.md / CLAUDE.md / skill / hook 命令"),
    mcp: bool = typer.Option(False, "--mcp", help="同时写 .mcp.json，让支持 MCP 的 agent 用 dsflow mcp 工具"),
    venv: bool = typer.Option(False, "--venv", help="同时准备分析环境：项目里的 .venv、基础分析库、挂上 dsflow"),
) -> None:
    """把一个已有项目接进平台：装 AGENTS.md、CLAUDE.md、dsflow-project skill、导读体检 hook，登记为可写。"""
    from .attach import attach

    try:
        for line in attach(path, python=python, force=force, mcp=mcp):
            typer.echo(line)
    except ProjectError as exc:
        _fail(exc)
    if venv:
        _prepare_env(path.resolve())


@app.command("call")
def call_cmd(
    tool: str = typer.Argument(..., help="工具名，见 dsflow protocol"),
    args: str = typer.Option("{}", "--args", help="参数 JSON"),
    project: Path | None = typer.Option(None, "--project", "-p", help="项目目录或 id（写进参数 project）"),
) -> None:
    """按协议调用一个工具，stdout 一行 JSON 信封。这是命令行传输，和 MCP、HTTP 用同一份登记表。"""
    from .protocol import call, envelope_error

    try:
        payload = json.loads(args or "{}")
    except json.JSONDecodeError as exc:
        typer.echo(json.dumps(envelope_error("invalid", f"--args 不是合法 JSON：{exc}"), ensure_ascii=False))
        raise typer.Exit(1) from None
    if project is not None:
        payload.setdefault("project", str(project))
    out = call(tool, payload)
    typer.echo(json.dumps(out, ensure_ascii=False, default=str))
    raise typer.Exit(0 if out["ok"] else 1)


@app.command("protocol")
def protocol_cmd(
    fmt: str = typer.Option("text", "--format", help="text / json / markdown"),
) -> None:
    """DSFlow Agent Protocol：状态机、文件契约、全部工具及参数（json 给 agent 读，markdown 生成文档）。"""
    from .core.rules import rules_markdown
    from .protocol import protocol_document, protocol_markdown

    doc = protocol_document()
    if fmt == "json":
        typer.echo(json.dumps(doc, ensure_ascii=False, indent=2))
    elif fmt == "markdown":
        typer.echo(rules_markdown())
        typer.echo(protocol_markdown())
    else:
        typer.echo(f"DSFlow Agent Protocol v{doc['protocol']} · {len(doc['tools'])} 个工具")
        typer.echo("工作规矩：")
        for i, r in enumerate(doc["rules"], 1):
            typer.echo(f"  {i}. {r['title']}：{r['rule']}")
        for group in dict.fromkeys(t["group"] for t in doc["tools"]):
            typer.echo(f"[{group}] " + "、".join(t["name"] for t in doc["tools"] if t["group"] == group))
        typer.echo(f"详情：{cli_prefix()} protocol --format markdown；调用：{cli_prefix()} call <工具> --args '{{…}}'")


@app.command("mcp")
def mcp_cmd() -> None:
    """以 MCP 服务（stdio）暴露协议里的全部工具（dsflow protocol 可查）。
    需要 `uv sync --extra mcp`；由 .mcp.json 或插件启动，不要手动在终端里跑。"""
    from .mcp_server import serve

    try:
        serve()
    except ProjectError as exc:
        _fail(exc)


hook_app = typer.Typer(help="Claude Code hook 的入口（由 .claude/settings.json 调用）", hidden=True)
app.add_typer(hook_app, name="hook")


@hook_app.command("guide-lint")
def hook_guide_lint() -> None:
    """读 stdin 里的 hook 事件；改的是导读就体检，不通过退出码 2。"""
    from .hooks import guide_lint

    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        raise typer.Exit(0) from None
    code, message = guide_lint(event)
    if message:
        typer.echo(message, err=True)
    raise typer.Exit(code)


@app.command()
def validate(path: Path = typer.Argument(Path("."), help="项目目录")) -> None:
    """按注册表规则校验项目（只读）。"""
    try:
        reg, issues = Project(path).load()
    except ProjectError as exc:
        typer.echo(f"无法读取项目：{exc}")
        raise typer.Exit(1) from exc
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        typer.echo(f"校验失败：{len(errors)} 个问题")
        for issue in errors:
            typer.echo(f"  - {issue.message}")
        raise typer.Exit(1)
    typer.echo(f"校验通过：{len(reg.steps)} 个步骤，{len(reg.stages)} 个阶段，{len(reg.groups)} 个折叠组")


@app.command("import")
def import_project(
    path: Path,
    writable: bool = typer.Option(False, "--writable", help="允许平台写入该项目的 .dsflow/（默认只读）"),
) -> None:
    """登记一个已有项目到平台。默认只读：平台不会在项目目录写入任何文件。"""
    try:
        row = PlatformIndex().add_project(path, readonly=not writable)
    except ProjectError as exc:
        typer.echo(f"无法登记：{exc}")
        raise typer.Exit(1) from exc
    mode = "只读" if row["readonly"] else "可写"
    typer.echo(f"已登记「{row['name']}」（{mode}），id={row['id']}")
    typer.echo(f"  {row['step_count']} 个步骤，校验问题 {row['error_count']} 个")


@app.command()
def projects() -> None:
    """列出已登记的项目。"""
    rows = PlatformIndex().list_projects()
    if not rows:
        typer.echo(f"还没有登记项目。用 {cli_prefix()} init <目录> --name 名称 新建，或 {cli_prefix()} attach <目录> 接入已有项目。")
    for row in rows:
        mode = "只读" if row["readonly"] else "可写"
        typer.echo(f"{row['id']}  {row['name']}（{mode}，{row['step_count']} 步）  {row['root']}")


@app.command()
def remove(project_id: str) -> None:
    """注销一个项目（只删登记，不动项目文件）。"""
    if not PlatformIndex().remove_project(project_id):
        typer.echo(f"未找到项目 {project_id}")
        raise typer.Exit(1)
    typer.echo(f"已注销 {project_id}；项目文件未改动。")


@app.command()
def schema(out: Path = typer.Option(REPO_ROOT / "docs" / "contracts", help="输出目录")) -> None:
    """导出全部数据契约的 JSON Schema。"""
    out.mkdir(parents=True, exist_ok=True)
    for name, model in CONTRACTS.items():
        text = json.dumps(model.model_json_schema(by_alias=True), ensure_ascii=False, indent=2)
        (out / f"{name}.schema.json").write_text(text + "\n", encoding="utf-8")
    typer.echo(f"已导出 {len(CONTRACTS)} 个契约到 {out}")


data_app = typer.Typer(help="数据视图：登记、画像、对比", no_args_is_help=True)
app.add_typer(data_app, name="data")


def _open(project_dir: Path) -> Project:
    """已登记的项目沿用登记时的读写模式；未登记的一律只读。"""
    project = Project(project_dir)
    row = PlatformIndex().get_project(project.id)
    return Project(project_dir, row["readonly"]) if row else project


def _fail(exc: Exception) -> None:
    typer.echo(f"失败：{exc}")
    raise typer.Exit(1) from exc


def _prepare_env(target: Path) -> None:
    """准备项目的分析环境。装不上（多半是没网）不算建项目失败，只提示重跑哪条命令。"""
    from .env import EnvError, prepare

    typer.echo("  正在准备分析环境（agent 执行代码用的 Python），第一次要联网下载，约一到几分钟……")
    try:
        for line in prepare(target):
            typer.echo(f"  {line}")
    except EnvError as exc:
        typer.echo(f"  分析环境没准备成：{exc}")
        typer.echo(f"  项目本身已经建好了。联网后重跑这条补上：{cli_prefix()} attach \"{target}\" --venv")


@data_app.command("add")
def data_add(
    project_dir: Path,
    path: str = typer.Argument(..., help="项目内的数据文件相对路径"),
    name: str = typer.Option(..., "--name", help="数据集逻辑名"),
    stage: str = typer.Option("raw", help="阶段：raw / processed / features / splits / model_input / predictions / other"),
    parent: list[str] = typer.Option([], "--parent", help="上游数据集名，可重复"),
    produced_by: str | None = typer.Option(None, "--produced-by", help="产出它的步骤编号"),
    description: str = typer.Option("", help="一句话介绍：一行代表什么、怎么来的、后面哪一步会用（第一次登记这个名字时必填）"),
    replaces: list[str] = typer.Option([], "--replaces", help="它登记后就不再有用的数据集名（退出存量），可重复"),
) -> None:
    """登记一个数据集版本（只记录路径与哈希，不复制数据）。"""
    from .data.datasets import DatasetStore
    from .data.engine import DataError

    try:
        out = DatasetStore(_open(project_dir)).register(path, name, stage, parent, produced_by, description, replaces)
    except (DataError, ProjectError, FileNotFoundError) as exc:
        _fail(exc)
    v = out["version"]
    state = "新版本" if out["created"] else "内容未变，沿用已有版本"
    typer.echo(f"{name} · {v['version']}（{state}）  {v['path']}  {v['size_bytes']:,} 字节")


@data_app.command("describe")
def data_describe(
    project_dir: Path,
    name: str = typer.Argument(..., help="已登记的数据集名"),
    description: str = typer.Argument(..., help="一句话介绍：装的是什么、怎么来的、后面哪一步会用"),
) -> None:
    """补写或改写一份数据的介绍（数据里文件名下面那行小字），不必重新登记。"""
    from .data.datasets import DatasetStore
    from .data.engine import DataError

    try:
        DatasetStore(_open(project_dir)).describe(name, description)
    except (DataError, ProjectError) as exc:
        _fail(exc)
    typer.echo(f"{name} 的介绍已写好：{description.strip()}")


@data_app.command("replace")
def data_replace(
    project_dir: Path,
    name: str = typer.Argument(..., help="新的、以后该用的数据集名"),
    old: list[str] = typer.Option(..., "--old", help="被它替代、不再是有用最终文件的数据集名，可重复"),
) -> None:
    """声明替代关系：新表登记之后，旧表退出「后存量」。产物只算有用的最终文件，被替代的不再算。"""
    from .data.datasets import DatasetStore
    from .data.engine import DataError

    try:
        DatasetStore(_open(project_dir)).set_replaces(name, old)
    except (DataError, ProjectError) as exc:
        _fail(exc)
    typer.echo(f"{name} 替代 {'、'.join(old)}")


@data_app.command("sync")
def data_sync(project_dir: Path) -> None:
    """把 dsflow.yaml 里声明的数据集全部登记一遍。"""
    from .data.datasets import DatasetStore

    project = _open(project_dir)
    declared = project.config.datasets if project.config else []
    if not declared:
        typer.echo("dsflow.yaml 没有声明数据集。")
        return
    store = DatasetStore(project)
    for d in declared:
        try:
            out = store.register(d.path, d.name, d.stage, description=d.description)
            typer.echo(f"{d.name} · {out['version']['version']}（{'新版本' if out['created'] else '未变'}）")
        except Exception as exc:  # noqa: BLE001 — 逐个报告，不因一个失败中断
            typer.echo(f"{d.name}：失败 {exc}")


@data_app.command("link")
def data_link(
    project_dir: Path,
    name: str = typer.Argument(..., help="已登记的数据集名"),
    step: str = typer.Option(..., "--step", help="步骤编号"),
    role: str = typer.Option("读取", "--role", help="用途：核对 / 读取 / 输入 / 产出"),
) -> None:
    """登记「某一步用了这张表」。校验型步骤不产出数据，只能靠这个挂到数据主线上。"""
    from .data.datasets import DatasetStore
    from .data.engine import DataError

    try:
        DatasetStore(_open(project_dir)).link(name, step, role)
    except (DataError, ProjectError) as exc:
        _fail(exc)
    typer.echo(f"{name} ← {step}（{role}）")


@data_app.command("list")
def data_list(project_dir: Path) -> None:
    """列出已登记的数据集（按阶段排列的演变链）。"""
    from .data.datasets import DatasetStore

    chain = DatasetStore(_open(project_dir)).chain()
    if not chain:
        typer.echo("还没有登记数据集。")
    for item in chain:
        shape = f"{item['rows']:,} 行 × {item['columns']} 列" if item["rows"] is not None else "未转换"
        typer.echo(f"[{item['stage_label']}] {item['name']} · {item['version']}（{shape}，共 {item['version_count']} 版）  {item['path']}")


@data_app.command("verify")
def data_verify(project_dir: Path, path: str, sha256: str) -> None:
    """核对数据文件的内容哈希是否与记录一致（复现前确认用的是同一份数据）。"""
    from .core.hashing import sha256_file

    try:
        target = Project(project_dir).resolve(path)
    except ProjectError as exc:
        _fail(exc)
    if not target.is_file():
        _fail(FileNotFoundError(path))
    actual = sha256_file(target)
    if actual != sha256:
        typer.echo(f"不一致：{path}\n  记录 {sha256}\n  现在 {actual}")
        raise typer.Exit(1)
    typer.echo(f"一致：{path}（{sha256[:12]}）")


@data_app.command("profile")
def data_profile(project_dir: Path, path: str) -> None:
    """生成数据画像并打印摘要。"""
    from .data.cache import DataCache
    from .data.service import ensure_profile

    try:
        report = ensure_profile(DataCache(_open(project_dir)), path)
    except Exception as exc:  # noqa: BLE001
        _fail(exc)
    typer.echo(f"{path}：{report['rows']:,} 行 × {report['column_count']} 列（画像耗时 {report['seconds']} 秒）")
    worst = sorted(report["columns"], key=lambda c: -c["null_rate"])[:5]
    for c in worst:
        if c["null_count"]:
            typer.echo(f"  缺失最多：{c['name']} {c['null_count']:,} 行（{c['null_rate']:.1%}）")


@data_app.command("compare")
def data_compare(
    project_dir: Path, a: str, b: str,
    key: list[str] = typer.Option([], "--key", help="主键列，可重复"),
    segment: str | None = typer.Option(None, help="分组列"),
) -> None:
    """对比两份数据：结构、行数、逐列变化；可选按主键对齐、按分组看变化集中在哪里。"""
    from .data.cache import DataCache
    from .server.data_routes import CompareIn, _compare_job

    try:
        r = _compare_job(DataCache(_open(project_dir)), CompareIn(a=a, b=b, key=key, segment=segment), lambda f, m: None)
    except Exception as exc:  # noqa: BLE001
        _fail(exc)
    rows, s = r["rows"], r["schema"]
    typer.echo(f"行数 {rows['a']:,} → {rows['b']:,}（{rows['delta']:+,}）；列数 {r['column_count']['a']} → {r['column_count']['b']}")
    if s["added"]:
        typer.echo(f"  新增列：{'、'.join(s['added'])}")
    if s["removed"]:
        typer.echo(f"  删除列：{'、'.join(s['removed'])}")
    typer.echo(f"  共同列中有变化的：{r['changed_columns']} 列")
    if "key" in r:
        k = r["key"]
        typer.echo(f"  按 {'、'.join(k['keys'])} 对齐：只在 A {k['only_a']:,}，只在 B {k['only_b']:,}，两边都有 {k['matched']:,}")
        if "changed_rows" in k:
            typer.echo(f"  两边都有的行中取值改变：{k['changed_rows']:,} 行")
    if "segment" in r:
        for row in r["segment"]["rows"][:5]:
            typer.echo(f"  {r['segment']['column']}={row['value']}：{row['a']:,} → {row['b']:,}（{row['delta']:+,}）")


@app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run_cmd(
    ctx: typer.Context,
    step: str = typer.Argument(..., help="步骤编号，如 1.2"),
    project: Path = typer.Option(Path("."), "--project", "-p", help="项目目录"),
    hypothesis: str = typer.Option("", "--hypothesis", help="这次运行要验证的假设"),
    revision: str | None = typer.Option(None, "--revision", help="轮次编号，如 r02"),
) -> None:
    """运行一条命令并记录为一次运行：dsflow run 1.2 -p 项目目录 -- uv run python src/clean.py"""
    from .index.db import open_for_write
    from .tracking.runner import execute, prepare

    argv = list(ctx.args)
    if not argv:
        typer.echo(f"用法：{cli_prefix()} run <步骤编号> -p <项目目录> -- <命令>")
        raise typer.Exit(2)
    try:
        proj = open_for_write(project)
    except ProjectError as exc:
        _fail(exc)
    run = prepare(proj, step, argv, hypothesis=hypothesis, revision=revision, source="cli")
    typer.echo(f"运行 {run['run_id']} 开始：{run['command']}")
    final = execute(proj, run["run_id"], on_line=lambda line: (sys.stdout.write(line), sys.stdout.flush()))
    state = "成功" if final["status"] == "succeeded" else "失败"
    typer.echo(f"运行 {final['run_id']} {state}（退出码 {final.get('exit_code')}，用时 {final.get('duration_s')} 秒）")
    raise typer.Exit(0 if final["status"] == "succeeded" else 1)


@app.command("runs")
def runs_cmd(
    project: Path = typer.Argument(Path("."), help="项目目录"),
    step: str | None = typer.Option(None, "--step", help="只看某个步骤"),
    limit: int = typer.Option(20, help="最多显示几条"),
) -> None:
    """列出最近的运行记录。"""
    from .index.db import open_for_write
    from .tracking.store import RunStore

    rows = RunStore(open_for_write(project)).list(step)[:limit]
    if not rows:
        typer.echo("还没有运行记录。")
    for r in rows:
        metrics = "，".join(f"{k}={v}" for k, v in list(r["metrics"].items())[:3])
        typer.echo(f"{r['run_id']}  {r['step']}  {r['status']}  {r.get('validity') or ''}  {metrics}  {r.get('conclusion') or r.get('hypothesis')}")


model_app = typer.Typer(help="模型登记：候选 → 已验收 → 已交付", no_args_is_help=True)
app.add_typer(model_app, name="model")
delivery_app = typer.Typer(help="交付清单：生成、刷新、核对", no_args_is_help=True)
app.add_typer(delivery_app, name="delivery")


def _models(project_dir: Path):
    from .delivery.models import ModelStore
    from .index.db import open_for_write

    try:
        project = open_for_write(project_dir)
    except ProjectError as exc:
        _fail(exc)
    return project, ModelStore(project)


@model_app.command("add")
def model_add(
    project_dir: Path,
    path: str = typer.Argument(..., help="项目内的模型文件相对路径"),
    name: str = typer.Option(..., "--name", help="模型名"),
    run: str | None = typer.Option(None, "--run", help="产出这个模型的运行编号（没有它就无法追溯数据与指标）"),
    description: str = typer.Option("", help="一句话说明"),
) -> None:
    """登记一个模型文件为候选版本（在代码里用 run.log_model 更方便，会自动关联运行）。"""
    from .delivery.models import ModelError

    _, store = _models(project_dir)
    try:
        out = store.register(path, name, run, description)
    except (ModelError, FileNotFoundError) as exc:
        _fail(exc)
    v = out["version"]
    typer.echo(f"{name} · {v['version']}（{'新版本，候选' if out['created'] else '内容未变，沿用已有版本'}）  {v['path']}")


@model_app.command("list")
def model_list(project_dir: Path = typer.Argument(Path("."), help="项目目录")) -> None:
    """列出登记的模型版本。"""
    _, store = _models(project_dir)
    models = store.list()
    if not models:
        typer.echo("还没有登记模型。")
    for m in models:
        for v in m["versions"]:
            metrics = "，".join(f"{k}={val}" for k, val in list(((v["run"] or {}).get("metrics") or {}).items())[:3])
            typer.echo(f"{m['name']} · {v['version']}  {v['status_label']}  步骤 {v.get('step') or '—'}  运行 {v.get('run_id') or '—'}  {metrics}")


@model_app.command("promote")
def model_promote(
    project_dir: Path, name: str, version: str,
    to: str = typer.Option(..., "--to", help="accepted（已验收）/ delivered（已交付）/ candidate（退回候选）"),
    note: str = typer.Option(..., "--note", help="理由，记入历史"),
) -> None:
    """变更模型状态。往上走要过门槛（产出运行有效、数据已登记、文件未改；交付还要交付清单齐全）。"""
    from .delivery.models import ModelError

    _, store = _models(project_dir)
    try:
        v = store.promote(name, version, to, note)
    except ModelError as exc:
        _fail(exc)
    except KeyError:
        _fail(KeyError(f"模型 {name} 没有版本 {version}"))
    typer.echo(f"{name} · {version} → {v['status_label']}")


def _pick(store, name: str, version: str | None) -> dict:
    try:
        return store.get(name, version) if version else store.latest(name)
    except KeyError:
        _fail(KeyError(f"模型 {name} 没有登记{f'版本 {version}' if version else ''}"))


def _print_checklist(report: dict) -> None:
    typer.echo(f"交付清单 {report['path']}：{report['summary']}（{report['passed']}/{report['total']} 项通过）")
    for item in report["items"]:
        if not item["passed"]:
            typer.echo(f"  - 未通过：{item['label']}{'：' + item['detail'] if item['detail'] else ''}")
    for note in report["notes"]:
        typer.echo(f"  · {note}")


@delivery_app.command("init")
def delivery_init(
    project_dir: Path, name: str,
    version: str | None = typer.Option(None, "--version", help="模型版本，默认最新登记的"),
) -> None:
    """生成或刷新 delivery/<模型名>/checklist.yaml：事实部分按登记与运行记录重写，人写的部分保留。"""
    from .delivery.checklist import check_checklist, draft_checklist, load_checklist, write_checklist

    project, store = _models(project_dir)
    v = _pick(store, name, version)
    existing, error = load_checklist(project, name)
    if error:
        _fail(ValueError(f"{error}；先修好文件再刷新"))
    try:
        rel = write_checklist(project, draft_checklist(project, v, existing))
    except ProjectError as exc:
        _fail(exc)
    typer.echo(f"{'已刷新' if existing else '已生成'} {rel}（{name} · {v['version']}）")
    _print_checklist(check_checklist(project, v))


@delivery_app.command("check")
def delivery_check(
    project_dir: Path, name: str,
    version: str | None = typer.Option(None, "--version", help="模型版本，默认最新登记的"),
) -> None:
    """核对交付清单；不齐全时退出码为 1。"""
    from .delivery.checklist import check_checklist

    project, store = _models(project_dir)
    report = check_checklist(project, _pick(store, name, version))
    _print_checklist(report)
    raise typer.Exit(0 if report["complete"] else 1)


guide_app = typer.Typer(help="notebook 导读：生成骨架、核对、放到平台读得到的位置", no_args_is_help=True)
app.add_typer(guide_app, name="guide")


def _guide_ctx(project_dir: Path):
    from .index.db import open_for_write

    try:
        project = open_for_write(project_dir)
        reg, _ = project.load()
    except ProjectError as exc:
        _fail(exc)
    if reg is None:
        _fail(ValueError("注册表无法解析，先跑 dsflow validate"))
    return project, reg


def _print_guide_checks(report: dict) -> None:
    for e in report["errors"]:
        typer.echo(f"  - 引用有误：{e}")
    typer.echo(f"  数字核对：{report['found']}/{report['checked']} 个数字在所引用单元格的代码或输出里找到")
    for m in report["missing"]:
        typer.echo(f"  - 没找到：{m['number']}（{m['where']}）——照输出原样写，或说明它是推算出来的")


@guide_app.command("init")
def guide_init(
    project_dir: Path,
    step: str = typer.Argument(..., help="步骤编号，如 1.1"),
    rev: str | None = typer.Option(None, "--rev", help="轮次，默认当前轮次"),
    notebook: str | None = typer.Option(None, "--notebook", help="本轮有多个 notebook 时指定一个"),
    out: Path | None = typer.Option(None, "--out", help="写到指定文件；不写就写到平台读得到的位置"),
) -> None:
    """按 notebook 的真实单元格生成导读骨架（每格列出行数与第一行，讲解内容由 agent 填）。"""
    from .explain.guide import GuideError, find_step, pick_revision, scaffold, write_target

    project, reg = _guide_ctx(project_dir)
    try:
        text = scaffold(project, reg, step, rev, notebook)
        target = out or write_target(project, pick_revision(find_step(reg, step), rev), step)
    except (GuideError, KeyError) as exc:
        _fail(exc)
    if target.exists():
        typer.echo(f"{target} 已存在，未覆盖。要重新生成就先改名或删除。")
        raise typer.Exit(1)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    typer.echo(f"已生成导读骨架：{target}")


@guide_app.command("check")
def guide_check(
    project_dir: Path = typer.Argument(Path("."), help="项目目录"),
    step: str | None = typer.Option(None, "--step", help="只核对某个步骤"),
) -> None:
    """核对导读：引用的 notebook、单元格、行号是否存在；讲解里的数字能否在输出里找到。引用有误时退出码为 1。"""
    from .core.steps import revisions_of
    from .explain.guide import check_guide, load_guide

    project, reg = _guide_ctx(project_dir)
    bad = 0
    found = False
    for s in reg.steps:
        if step and s.id != step:
            continue
        for r in revisions_of(s):
            guide, error, path, _ = load_guide(project, s, r)
            if error:
                typer.echo(f"{s.id} {r.id} {path}：{error}")
                bad += 1
                continue
            if guide is None:
                typer.echo(f"{s.id} {r.id} 还没有导读")
                continue
            found = True
            report = check_guide(project, reg, s, r, guide)
            typer.echo(f"{s.id} {r.id} 导读 {path}")
            _print_guide_checks(report)
            bad += len(report["errors"])
    if not found and not bad:
        typer.echo(f"还没有导读。用 {cli_prefix()} guide init <项目目录> <步骤> 生成骨架。")
    raise typer.Exit(1 if bad else 0)


@guide_app.command("put")
def guide_put(
    project_dir: Path,
    step: str = typer.Argument(..., help="步骤编号"),
    file: Path = typer.Argument(..., help="写好的导读文件"),
    rev: str | None = typer.Option(None, "--rev", help="轮次，默认当前轮次"),
) -> None:
    """把写好的导读放到平台读得到的位置：可写项目放轮次目录，只读项目放平台目录（项目目录不写入）。"""
    from .explain.guide import GuideError, put_guide

    project, reg = _guide_ctx(project_dir)
    try:
        target, report = put_guide(project, reg, step, file.read_text(encoding="utf-8"), rev)
    except (GuideError, KeyError, OSError) as exc:
        _fail(exc)
    typer.echo(f"已放到 {target}")
    _print_guide_checks(report)
    _lint_and_exit(project, reg, step)


def _lint_and_exit(project, reg, step: str | None) -> None:
    from .explain.lint import lint_project

    bad = 0
    for step_id, rev_id, issues in lint_project(project, reg, step):
        if not issues:
            typer.echo(f"{step_id} {rev_id} 用词与篇幅：通过")
            continue
        bad += len(issues)
        typer.echo(f"{step_id} {rev_id} 用词与篇幅：{len(issues)} 处要改")
        for issue in issues:
            typer.echo(f"  - {issue}")
    if bad:
        typer.echo(f"共 {bad} 处不通过。改完再放一次——不要绕过，说不清楚就等于没讲。")
        raise typer.Exit(1)


@guide_app.command("lint")
def guide_lint(
    project_dir: Path = typer.Argument(Path("."), help="项目目录"),
    step: str | None = typer.Option(None, "--step", help="只查某个步骤"),
) -> None:
    """导读体检：登记要避开的说法、开头四段的齐整与篇幅、有没有照搬报告。有一处不通过退出码就是 1。"""
    project, reg = _guide_ctx(project_dir)
    _lint_and_exit(project, reg, step)
    typer.echo("全部通过。")


LEVEL_LABEL = {"critical": "严重", "serious": "重要", "warning": "注意", "info": "提示"}


@app.command("check")
def check_cmd(
    project_dir: Path = typer.Argument(Path("."), help="项目目录"),
    step: str | None = typer.Option(None, "--step", help="只核对某个步骤的说明卡"),
) -> None:
    """交接前核对：告警（原始数据、注册表、运行、报告、状态、模型）+ 说明卡数字核对与术语检查。
    有严重 / 重要告警或数字不一致时退出码为 1。"""
    from .index.db import open_for_write
    from .progress.alerts import compute_alerts
    from .progress.checks import load_vocab, step_checks
    from .tracking.store import RunStore

    try:
        project = open_for_write(project_dir)
        reg, issues = project.load()
    except ProjectError as exc:
        _fail(exc)
    if reg is None:
        for i in issues:
            typer.echo(f"  - {i.message}")
        _fail(ValueError("注册表无法解析"))
    alerts = compute_alerts(project, reg, issues, RunStore(project).list(), verify=True)
    typer.echo(f"告警 {len(alerts)} 条" + ("" if alerts else "：没有"))
    for a in alerts:
        typer.echo(f"  [{LEVEL_LABEL[a['level']]}] {a['message']}")
    vocab = load_vocab(project)
    mismatched = 0
    for s in reg.steps:
        if step and s.id != step:
            continue
        r = step_checks(project, reg, s.id, vocab)
        if not r["has_card"]:
            continue
        n = r["numbers"]
        mismatched += sum(1 for x in n["items"] if x["status"] == "mismatch")
        typer.echo(f"{s.id} {r['revision']} 数字核对：{n['matched']}/{n['checked']} 一致，共 {n['total']} 个核心数字")
        for x in n["items"]:
            if x["status"] == "mismatch":
                typer.echo(f"  - 不一致：{x['label']} 卡上 {x['expected']}，产物里是 {x['actual']}")
            elif x["status"] == "error":
                typer.echo(f"  - 无法核对：{x['label']}：{x['detail']}")
        terms = r["terms"] or {}
        for t in terms.get("avoid", []):
            typer.echo(f"  - 术语：「{t['found']}」出现 {t['count']} 处，应统一为「{t['use']}」")
        if terms.get("unregistered"):
            typer.echo(f"  - 未登记的加粗词：{'、'.join(terms['unregistered'])}")
    blocking = [a for a in alerts if a["level"] in ("critical", "serious")]
    raise typer.Exit(1 if blocking or mismatched else 0)


@app.command("next")
def next_cmd(
    project_dir: Path = typer.Argument(Path("."), help="项目目录"),
    step: str | None = typer.Option(None, "--step", help="只看某个步骤（默认取顺序最靠前的进行中步骤）"),
    as_json: bool = typer.Option(False, "--json", help="只输出 JSON，给 agent 读"),
) -> None:
    """告诉 agent 项目在哪一步、这一步缺什么文件、下一步该做什么、该跑哪条命令。只读。"""
    from .core.next import PHASE_LABEL, next_action
    from .index.db import open_for_write

    try:
        project = open_for_write(project_dir)
        reg, issues = project.load()
    except ProjectError as exc:
        _fail(exc)
    if reg is None:
        for i in issues:
            typer.echo(f"  - {i.message}")
        _fail(ValueError("注册表无法解析"))
    try:
        result = next_action(project, reg, issues, step)
    except KeyError as exc:
        _fail(ValueError(f"注册表里没有步骤 {exc.args[0]}"))
    if as_json:
        typer.echo(json.dumps(result, ensure_ascii=False))
        return
    s = result["step"]
    if s is None:
        typer.echo(f"{result['project']['name']}：{PHASE_LABEL[result['phase']]}")
    else:
        typer.echo(f"{result['project']['name']} · 步骤 {s['id']} {s['title']}（{s['status_label']}，轮次 {s['revision']}）")
        typer.echo(f"现在处于：{PHASE_LABEL[result['phase']]}")
        if result["missing"]:
            typer.echo(f"本轮目录 {s['dir']} 还缺：{'、'.join(result['missing'])}")
    env = result["environment"]
    if env["checked"] and not env["ready"]:
        typer.echo(f"分析环境：{env['detail']}")
    for line in result["todo"]:
        typer.echo(f"  - {line}")
    if result["commands"]:
        typer.echo("该跑的命令：")
        for c in result["commands"]:
            typer.echo(f"  {c}")
    if result["issues"]:
        typer.echo("本步的校验问题：")
        for i in result["issues"]:
            typer.echo(f"  - {i['message']}")
    a = result["attention"]
    waiting = [f"待审批 {'、'.join(x['id'] for x in a['pending_approval'])}" if a["pending_approval"] else "",
               f"待验收 {'、'.join(x['id'] for x in a['awaiting_acceptance'])}" if a["awaiting_acceptance"] else ""]
    waiting = [w for w in waiting if w]
    if waiting:
        typer.echo("全项目：" + "；".join(waiting))


def _decide(project_dir: Path, step: str, decision: str, note: str, kind: str | None) -> None:
    from .core.approval import ApprovalError, decide, find_step, kind_for
    from .index.db import open_for_write

    try:
        project = open_for_write(project_dir)
        reg, _ = project.load()
        if reg is None:
            raise ProjectError("注册表无法解析")
        k = kind or kind_for(find_step(reg, step))
        result = decide(project, reg, step, k, decision, note, source="命令行")
    except (ProjectError, ApprovalError) as exc:
        _fail(exc)
    e = result["entry"]
    typer.echo(f"{step} · {e['kind_label']}{e['decision_label']}：{result['from']} → {result['to']}，已记入 {result['record']}")
    for w in result["warnings"]:
        typer.echo(f"  注意：{w}")


@app.command()
def approve(
    project_dir: Path = typer.Argument(Path("."), help="项目目录"),
    step: str = typer.Argument(..., help="步骤编号"),
    note: str = typer.Option("", "--note", help="用户的原话"),
) -> None:
    """记录用户「通过」：待审批 → 进行中；待验收时等同 confirm（→ 已完成）。用户在对话里表态后由主 agent 运行。"""
    _decide(project_dir, step, "approve", note, None)


@app.command()
def reject(
    project_dir: Path = typer.Argument(Path("."), help="项目目录"),
    step: str = typer.Argument(..., help="步骤编号"),
    note: str = typer.Option("", "--note", help="用户的原话：为什么退回、要改什么"),
) -> None:
    """记录用户「退回」：待审批的留在待审批；待验收的退回进行中。"""
    _decide(project_dir, step, "reject", note, None)


@app.command()
def withdraw(
    project_dir: Path = typer.Argument(Path("."), help="项目目录"),
    step: str = typer.Argument(..., help="步骤编号"),
    note: str = typer.Option("", "--note", help="用户的原话：为什么撤回"),
) -> None:
    """撤回这一步最后一条审批：状态改回表态之前，审批记录里追加一条「撤回」（记录从不删除）。

    只能撤最后一条，而且这一步的状态还停在那条记录留下的状态；已经接着往下做了就撤不了。"""
    from .core.approval import ApprovalError, withdraw as do_withdraw
    from .index.db import open_for_write

    try:
        project = open_for_write(project_dir)
        reg, _ = project.load()
        if reg is None:
            raise ProjectError("注册表无法解析")
        result = do_withdraw(project, reg, step, note, source="命令行")
    except (ProjectError, ApprovalError) as exc:
        _fail(exc)
    w = result["withdrew"]
    typer.echo(f"{step} · 已撤回 {w['time']} 的「{w['decision_label']} · {w['kind_label']}」："
               f"{result['from']} → {result['to']}，已记入 {result['record']}")


@app.command()
def confirm(
    project_dir: Path = typer.Argument(Path("."), help="项目目录"),
    step: str = typer.Argument(..., help="步骤编号"),
    note: str = typer.Option("", "--note", help="用户的原话"),
) -> None:
    """记录用户「确认完成」：待验收 → 已完成。"""
    _decide(project_dir, step, "approve", note, "acceptance")


@app.command("await")
def await_cmd(
    project_dir: Path = typer.Argument(Path("."), help="项目目录"),
    step: str = typer.Argument(..., help="步骤编号"),
    kind: str = typer.Option("any", "--kind", help="any / approval / acceptance"),
    timeout: float = typer.Option(3600, "--timeout", help="最多等多少秒"),
    interval: float = typer.Option(2.0, "--interval", help="每隔多少秒看一次文件"),
) -> None:
    """阻塞到用户在平台或对话里审批 / 确认为止。stdout 一行 JSON；退出码 0 通过或确认、3 退回、4 超时。

    主 agent 交完计划后用后台方式运行它，命令退出即被唤醒，然后按 skill 规则继续（默认两个角色同一个 agent；用户另行安排了执行 agent 就交给它）。"""
    from .core.approval import ApprovalError, wait_for
    from .index.db import open_for_write

    try:
        project = open_for_write(project_dir)
        result = wait_for(project, step, kind, timeout, interval)
    except (ProjectError, ApprovalError) as exc:
        _fail(exc)
    typer.echo(json.dumps(result, ensure_ascii=False))
    raise typer.Exit({"rejected": 3, "timeout": 4}.get(result["result"], 0))


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


@app.command()
def ui(
    port: int = typer.Option(8790, help="端口（网页、API、/mcp 同一个端口）"),
    host: str = typer.Option("127.0.0.1", help="监听地址；给远程 agent 用时设 0.0.0.0，并必须带 --token 或 DSFLOW_TOKEN"),
    token: str | None = typer.Option(None, "--token", help="非本机访问 /mcp 与 /api 时要带的令牌（Authorization: Bearer …）；默认读环境变量 DSFLOW_TOKEN"),
    dev: bool = typer.Option(False, "--dev", help="同时启动 Vite 开发服务器（前端热更新）"),
    browser: bool = typer.Option(True, "--browser/--no-browser", help="启动后打开浏览器"),
) -> None:
    """启动平台：网页 + HTTP API + MCP（/mcp，streamable HTTP）。"""
    import os

    import uvicorn

    from .server.app import create_app

    token = token or os.environ.get("DSFLOW_TOKEN") or None
    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        typer.echo(f"监听非本机地址必须设令牌：{cli_prefix()} ui --host 0.0.0.0 --token <随机字符串>（或环境变量 DSFLOW_TOKEN）")
        raise typer.Exit(1)
    if not _port_free(port):
        typer.echo(f"端口 {port} 已被其他程序占用，请换一个：{cli_prefix()} ui --port <端口>")
        raise typer.Exit(1)
    url = f"http://127.0.0.1:{port}"
    children: list[subprocess.Popen] = []
    if dev:
        web = str(REPO_ROOT / "web")
        pnpm, npm = shutil.which("pnpm"), shutil.which("npm")
        if pnpm:
            argv = [pnpm, "--dir", web, "dev"]
        elif npm:
            argv = [npm, "--prefix", web, "run", "dev"]
        else:
            typer.echo("--dev 要用 pnpm 或 npm 启动前端开发服务器，两个都没找到。装 Node.js（自带 npm）后重试；不加 --dev 只要构建过网页就能用。")
            raise typer.Exit(1)
        env = {**os.environ, "DSFLOW_API_PORT": str(port)}
        children.append(subprocess.Popen(argv, env=env))
        url = "http://127.0.0.1:5173"
    elif not (web_dist() / "index.html").is_file():
        typer.echo(f"前端尚未构建：先在仓库运行 npm --prefix web install && npm --prefix web run build（用 pnpm 也行），或使用 {cli_prefix()} ui --dev。现在只启动 API 与 /mcp。")
    if browser:
        threading.Timer(2.0, webbrowser.open, args=[url]).start()
    application = create_app(token=token, mcp_host=host)
    mcp_note = "，MCP：" + url + "/mcp" if getattr(application.state, "mcp", False) else "（MCP 未装：uv sync --extra mcp）"
    typer.echo(f"DSFlow 已启动：{url}{mcp_note}" + ("，已启用令牌" if token else "") + "（Ctrl+C 退出）")
    try:
        uvicorn.run(application, host=host, port=port, log_level="warning")
    finally:
        for child in children:
            child.terminate()


@app.command()
def chat(
    project: Path | None = typer.Argument(None, help="项目目录或 id（也可以进去以后 /project 选）"),
    model: str | None = typer.Option(None, "--model", help="用哪个配好的模型（默认当前）"),
    plain: bool = typer.Option(False, "--plain", help="纯文本模式，不画全屏界面"),
) -> None:
    """终端对话客户端：配好你自己的大模型（/models add），在终端里和它推进项目，它通过协议工具在平台上生成信息。"""
    try:
        from .chat.commands import ChatState
    except ImportError as exc:
        _fail(ProjectError(f"缺少依赖：{exc}；仓库形态 uv sync --extra chat，安装包形态 uv tool install \".[mcp,chat]\""))
    from .chat.agent import project_info
    from .chat.config import ModelConfigError

    state = ChatState()
    try:
        if model:
            state.entry = state.config.get(model)
        else:
            state.entry = state.config.active()
        if project is not None:
            state.project = project_info(str(project))
    except (ModelConfigError, ProjectError) as exc:
        _fail(exc)
    if plain:
        from .chat.plain import run_plain

        run_plain(state)
        return
    from .chat.tui import ChatApp

    ChatApp(state).run()


models_app = typer.Typer(help="终端客户端要用的大模型：增删、切换、测连通（和 /models 命令一样，存在平台目录 models.json）", no_args_is_help=True)
app.add_typer(models_app, name="models")


@models_app.command("add")
def models_add(
    name: str = typer.Argument(..., help="给这个配置起的名字"),
    preset: str | None = typer.Option(None, "--preset", help="anthropic / openai / deepseek / qwen / moonshot / zhipu / openrouter / ollama"),
    provider: str | None = typer.Option(None, "--provider", help="anthropic 或 openai（OpenAI 兼容）"),
    base_url: str | None = typer.Option(None, "--base-url"),
    model: str | None = typer.Option(None, "--model", help="模型 ID"),
    api_key: str | None = typer.Option(None, "--api-key", help="密钥，或 env:变量名"),
    set_active: bool = typer.Option(False, "--set-active"),
) -> None:
    """例：dsflow models add 我的deepseek --preset deepseek --api-key sk-… --set-active"""
    from .chat.config import ModelConfig, ModelConfigError

    try:
        e = ModelConfig().add(name, preset=preset, provider=provider, base_url=base_url, model=model, api_key=api_key, set_active=set_active)
    except ModelConfigError as exc:
        _fail(exc)
    typer.echo(f"已保存 {e.name}：{e.provider} · {e.model}  {e.base_url or ''}  密钥 {e.masked_key()}")


@models_app.command("list")
def models_list() -> None:
    from .chat.config import ModelConfig

    cfg = ModelConfig()
    active = cfg.active()
    rows = cfg.list()
    if not rows:
        typer.echo(f"还没有配置模型：{cli_prefix()} models add <名称> --preset <提供方> --api-key <密钥>")
    for r in rows:
        typer.echo(f"{'*' if active and r.name == active.name else ' '} {r.name}  {r.provider} · {r.model}  {r.base_url or ''}  密钥 {r.masked_key()}")


@models_app.command("use")
def models_use(name: str) -> None:
    from .chat.config import ModelConfig, ModelConfigError

    try:
        e = ModelConfig().use(name)
    except ModelConfigError as exc:
        _fail(exc)
    typer.echo(f"当前模型：{e.name}（{e.provider} · {e.model}）")


@models_app.command("remove")
def models_remove(name: str) -> None:
    from .chat.config import ModelConfig, ModelConfigError

    try:
        ModelConfig().remove(name)
    except ModelConfigError as exc:
        _fail(exc)
    typer.echo(f"已删除 {name}")


@models_app.command("status")
def models_status(name: str | None = typer.Argument(None, help="默认当前模型")) -> None:
    """发一句话测通不通。"""
    from .chat.config import ModelConfig, ModelConfigError
    from .chat.llm import LLMError, make_backend

    try:
        cfg = ModelConfig()
        e = cfg.get(name) if name else cfg.active()
        if e is None:
            raise ModelConfigError("还没有配置模型")
        turn = make_backend(e).complete("你是连通性测试。只回复：ok", [{"role": "user", "content": "在吗"}], [])
    except (ModelConfigError, LLMError, ImportError) as exc:
        _fail(exc)
    typer.echo(f"{e.name} 可用：模型回复「{turn.text.strip()[:40]}」，用量 {turn.usage}")


@app.command()
def demo(
    path: Path = typer.Argument(Path("dsflow-demo"), help="演示项目放在哪个空目录"),
    port: int = typer.Option(8790, help="平台端口（只用来拼网址）"),
) -> None:
    """三分钟看到整条链：建一个带计划、等审批的演示项目，然后照屏幕上的三步做。不需要 LLM。"""
    from .demo import make_demo

    try:
        info = make_demo(path)
    except ProjectError as exc:
        _fail(exc)
    root = info["root"].as_posix()  # 正斜杠：PowerShell、cmd、Git Bash 里都能原样粘贴
    P = cli_prefix()
    typer.echo(f"演示项目已建好：{root}（平台 id {info['id']}）")
    typer.echo("")
    typer.echo("接下来三步：")
    typer.echo(f"  1. 平台没开就开：{P} ui --no-browser   然后打开 http://127.0.0.1:{port}/p/{info['id']}/steps/1.1")
    typer.echo("     你会看到步骤 1.1 的计划，页头有一条橙色的审批条——这就是 agent 交完计划后你看到的样子。")
    typer.echo(f"  2. 另开一个终端，扮演 agent 等审批：{P} await \"{root}\" 1.1" + ("（在仓库目录里运行）" if P.startswith("uv run") else ""))
    typer.echo("  3. 回到网页，填一句原话，点「通过」。第 2 步的命令会立刻退出并打印你的原话——真实的 agent 就是这样被唤醒、接着执行的。")
    typer.echo("")
    typer.echo("接真实的 agent：在这个目录里启动它，说「这个项目用 DSFlow 追踪，先读 AGENTS.md，动手之前调 next，按它的 tool_calls 做」。")
    typer.echo(f"  演示项目不执行代码，所以没建分析环境；真要让 agent 在它上面跑代码，先运行：{P} attach \"{root}\" --venv")
    typer.echo(f"看不明白就运行 {P} doctor，每一条都带修法。")


@app.command()
def doctor(
    path: Path = typer.Argument(Path("."), help="要检查的项目目录（不是项目也没关系）"),
    as_json: bool = typer.Option(False, "--json", help="只输出 JSON"),
) -> None:
    """检查安装、平台目录、登记的项目、当前目录的接入情况，每一条都带修法。有严重问题时退出码 1。"""
    from .doctor import run_doctor

    report = run_doctor(path)
    if as_json:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        mark = {"ok": "✓", "warn": "!", "fail": "✗"}
        for item in report["checks"]:
            fix = f"\n    修法：{item['fix']}" if item.get("fix") and item["status"] != "ok" else ""
            typer.echo(f"{mark[item['status']]} {item['name']}：{item['detail']}{fix}")
        typer.echo(report["summary"])
    raise typer.Exit(1 if report["failed"] else 0)


if __name__ == "__main__":
    app()
