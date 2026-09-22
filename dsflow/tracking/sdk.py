"""运行追踪 SDK：在被管项目的代码里记录一次运行——用了什么数据、什么参数、为了验证什么假设、结论是什么。

    import dsflow

    with dsflow.start_run("1.2", hypothesis="重复行删除后按月需求量不失真") as run:
        run.log_input("data/raw/orders.csv", name="orders_raw")
        run.log_params({"去重键": "全部字段"})
        out = run.log_output(df, name="orders_clean", path="steps/01_数据预处理/1.2_订单清洗/outputs/orders_clean.parquet")
        run.log_metrics({"删除行数": 1830})
        run.set_conclusion("删除完全重复行 1,830 行，其余订单全部保留", validity="有效")

由 `dsflow run` 启动时（有环境变量 DSFLOW_RUN_ID），SDK 写进同一条运行记录；直接运行脚本时自己新建一条。
输出数据会自动登记为新版本（产出步骤 = 本步，上游 = 本次输入），并与每个输入生成对比摘要。
"""

from __future__ import annotations

import math
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

from ..core.hashing import sha256_file
from ..core.project import ProjectError
from ..data.compare import compare_profiles
from ..data.datasets import DatasetStore
from ..data.cache import DataCache
from ..data.engine import jsonable
from ..data.files import data_format
from ..data.service import ensure_profile
from ..index.db import open_for_write
from .store import RunStore

VALIDITY = ("有效", "无效", "无结论")


def find_root(start: Path) -> Path:
    for d in [start, *start.parents]:
        if (d / "dsflow.yaml").is_file() or (d / "lifecycle" / "steps.json").is_file():
            return d
    raise ProjectError(f"从 {start} 往上没有找到 DSFlow 项目（dsflow.yaml 或 lifecycle/steps.json）")


def _plain(v: Any) -> Any:
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()  # numpy 标量
        except (TypeError, ValueError):
            pass
    return jsonable(v)


def _metric(v: Any) -> float | None:
    try:
        f = float(_plain(v))
    except (TypeError, ValueError):
        raise ValueError(f"指标必须是数字：{v!r}") from None
    return f if math.isfinite(f) else None


class ActiveRun:
    def __init__(self, step: str, *, revision: str | None = None, hypothesis: str = "", project: str | Path | None = None):
        root = Path(project or os.environ.get("DSFLOW_PROJECT") or find_root(Path.cwd())).resolve()
        self.project = open_for_write(root)
        self.store = RunStore(self.project)
        env_id = os.environ.get("DSFLOW_RUN_ID")
        existing = self.store.get(env_id) if env_id else None
        self.attached = bool(existing and existing["step"] == step and existing["status"] == "running")
        if self.attached:
            self.run = existing
            self.run["hypothesis"] = self.run.get("hypothesis") or hypothesis
            self.run["revision"] = self.run.get("revision") or revision
        else:
            self.run = self.store.create(step, revision=revision, hypothesis=hypothesis,
                                         argv=[sys.executable, *sys.argv], cwd=os.getcwd(), source="sdk")
        self._save()

    # ---------- 上下文 ----------

    def __enter__(self) -> ActiveRun:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.run["error"] = "".join(traceback.format_exception_only(exc_type, exc)).strip()
        self._save()
        if not self.attached:
            self.run = self.store.finish(self.run["run_id"], "failed" if exc else "succeeded")
        return False

    def end(self, error: str = "") -> None:
        """结束这次运行：notebook 里用不了 with，在最后一格调用它。由 dsflow run 启动时，收尾交给平台。"""
        exc = RuntimeError(error) if error else None
        self.__exit__(type(exc) if exc else None, exc, None)

    @property
    def run_id(self) -> str:
        return self.run["run_id"]

    def _save(self) -> None:
        self.store.save(self.run)

    # ---------- 记录 ----------

    def log_params(self, params: dict[str, Any]) -> None:
        self.run["params"].update({str(k): _plain(v) for k, v in params.items()})
        self._save()

    def log_param(self, name: str, value: Any) -> None:
        self.log_params({name: value})

    def log_metrics(self, metrics: dict[str, Any], fold: str | int | None = None) -> None:
        """fold 不为空时记为逐折指标，便于看结果随切分的波动。"""
        values = {str(k): _metric(v) for k, v in metrics.items()}
        if fold is None:
            self.run["metrics"].update(values)
        else:
            self.run["fold_metrics"].setdefault(str(fold), {}).update(values)
        self._save()

    def log_metric(self, name: str, value: Any, fold: str | int | None = None) -> None:
        self.log_metrics({name: value}, fold)

    def set_hypothesis(self, text: str) -> None:
        self.run["hypothesis"] = text
        self._save()

    def set_conclusion(self, text: str, validity: str | None = None) -> None:
        """validity：有效 / 无效 / 无结论。无效和无结论的尝试同样要记下来。"""
        if validity is not None and validity not in VALIDITY:
            raise ValueError(f"validity 只能是 {' / '.join(VALIDITY)}")
        self.run["conclusion"] = text
        self.run["validity"] = validity
        self._save()

    def _abs(self, path: str | Path) -> Path:
        """相对路径按当前目录解析；当前目录不在项目里（例如从别处用 project= 指定项目），
        或按当前目录找不到而按项目根目录找得到（notebook 的当前目录是它自己所在的目录），都按项目根目录解析。"""
        p = Path(path)
        if p.is_absolute():
            return p.resolve()
        here = (Path.cwd() / p).resolve()
        root = (self.project.root / p).resolve()
        if here.is_relative_to(self.project.root) and (here.exists() or not root.exists()):
            return here
        return root

    def _rel(self, path: str | Path) -> str:
        p = self._abs(path)
        try:
            return p.relative_to(self.project.root).as_posix()
        except ValueError:
            raise ProjectError(f"{path} 不在项目目录 {self.project.root} 内") from None

    def _register(self, rel: str, name: str | None, stage: str | None, *, produced_by: str | None = None,
                  parents: list[str] | None = None, description: str = "", replaces: list[str] | None = None,
                  require_description: bool = True) -> dict:
        store = DatasetStore(self.project)
        name = name or Path(rel).stem
        existing = store.get(name)
        stage = stage or (existing["versions"][-1]["stage"] if existing else "raw")
        v = store.register(rel, name, stage, parents, produced_by, description, replaces,
                           require_description)["version"]
        return {"name": name, "version": v["version"], "path": v["path"], "sha256": v["sha256"],
                "rows": v.get("rows"), "columns": v.get("columns")}

    def _add(self, key: str, ref: dict) -> None:
        items = [r for r in self.run[key] if not (r["name"] == ref["name"] and r["version"] == ref["version"])]
        self.run[key] = [*items, ref]

    def log_input(self, path: str | Path, name: str | None = None, stage: str | None = None,
                  description: str = "") -> dict:
        """登记本次用到的输入数据（记录内容哈希，数据不复制）。

        description 是这份数据的简要介绍（页面上文件名下面那行小字）。读进来的表往往是别的步骤登记过的，
        所以这里不强制写；还没有人介绍过的表会在告警里提醒补上，用 data_describe 或这个参数都行。"""
        ref = self._register(self._rel(path), name, stage, description=description, require_description=False)
        self._add("inputs", ref)
        self._save()
        return ref

    def log_output(self, data: Any, name: str, path: str | Path | None = None, stage: str = "processed",
                   description: str = "", delta: bool = True, replaces: list[str] | None = None) -> dict:
        """登记输出数据。data 可以是文件路径，也可以是 DataFrame（此时要给 path，写成 parquet 或 csv）。
        description 是这份数据的简要介绍（一行代表什么、怎么来的、后面哪一步会用），第一次登记这个名字时必须写，
        页面上文件名下面那行小字就是它。
        delta=True 时，与本次每个输入生成结构、行数、逐列变化的对比摘要。
        replaces 写明它登记后哪些表就不再是有用的最终文件（比如清洗后的表替代原始表），它们会退出数据层的「后存量」。"""
        if isinstance(data, (str, Path)):
            rel = self._rel(data)
        else:
            if path is None:
                raise ValueError("传 DataFrame 时要给出保存路径 path（项目内，建议放在本步的 outputs/ 下）")
            target = self._abs(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            suffix = target.suffix.lower()
            if suffix == ".parquet" and hasattr(data, "to_parquet"):
                data.to_parquet(target, index=False)
            elif suffix == ".parquet" and hasattr(data, "write_parquet"):
                data.write_parquet(target)
            elif suffix == ".csv" and hasattr(data, "to_csv"):
                data.to_csv(target, index=False)
            else:
                raise ValueError("只支持把 DataFrame 保存为 .parquet 或 .csv")
            rel = self._rel(target)
        parents = [r["name"] for r in self.run["inputs"]]
        ref = self._register(rel, name, stage, produced_by=self.run["step"], parents=parents, description=description,
                             replaces=replaces)
        self._add("outputs", ref)
        if delta:
            self._delta(ref)
        self._save()
        return ref

    def _delta(self, out: dict) -> None:
        cache = DataCache(self.project)
        try:
            pb = ensure_profile(cache, out["path"])
        except Exception as exc:  # noqa: BLE001 — 对比失败不影响运行本身，如实记下
            self.run["deltas"].append({"output": out["name"], "error": f"无法生成输出画像：{exc}"})
            return
        for inp in self.run["inputs"]:
            if data_format(Path(inp["path"])) is None:
                continue
            try:
                r = compare_profiles(ensure_profile(cache, inp["path"]), pb)
            except Exception as exc:  # noqa: BLE001
                self.run["deltas"].append({"input": inp["name"], "output": out["name"], "error": str(exc)})
                continue
            self.run["deltas"].append({
                "input": inp["name"], "input_path": inp["path"], "output": out["name"], "output_path": out["path"],
                "rows_a": r["rows"]["a"], "rows_b": r["rows"]["b"], "row_delta": r["rows"]["delta"],
                "columns_a": r["column_count"]["a"], "columns_b": r["column_count"]["b"],
                "added": r["schema"]["added"], "removed": r["schema"]["removed"],
                "changed_columns": r["changed_columns"],
                "flagged": [c["name"] for c in r["columns"] if c["flags"]][:10],
            })

    def log_artifact(self, path: str | Path, purpose: str = "", kind: str = "other") -> dict:
        rel = self._rel(path)
        ref = {"path": rel, "purpose": purpose, "kind": kind, "sha256": sha256_file(self.project.root / rel)}
        self.run["artifacts"] = [a for a in self.run["artifacts"] if a["path"] != rel] + [ref]
        self._save()
        return ref

    def log_model(self, path: str | Path, name: str, description: str = "") -> dict:
        """把模型文件登记为一个模型版本（候选），关联本次运行：训练数据版本、代码版本、指标都从本次运行记录追溯。
        同样内容的文件只算一个版本。"""
        from ..delivery.models import ModelStore

        v = ModelStore(self.project).register(self._rel(path), name, run_id=self.run_id, description=description)["version"]
        ref = {"name": name, "version": v["version"], "path": v["path"]}
        self.run["models"] = [m for m in self.run.get("models", []) if (m["name"], m["version"]) != (name, v["version"])] + [ref]
        self._save()
        return ref

    def log_figure(self, figure: Any, name: str) -> str:
        """保存图表（任何有 savefig 方法的对象，如 matplotlib Figure）到运行记录目录。"""
        file = re.sub(r"[^\w一-鿿.-]+", "_", name).strip("_")[:60] + ".png"
        figure.savefig(self.store.artifacts_dir(self.run_id) / file, dpi=110, bbox_inches="tight")
        self.run["figures"] = [f for f in self.run["figures"] if f["file"] != file] + [{"name": name, "file": file}]
        self._save()
        return file


def start_run(step: str, *, revision: str | None = None, hypothesis: str = "", project: str | Path | None = None) -> ActiveRun:
    return ActiveRun(step, revision=revision, hypothesis=hypothesis, project=project)
