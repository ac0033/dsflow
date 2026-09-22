"""`dsflow mcp`：把协议登记表（dsflow/protocol.py）里的每个工具暴露为 MCP 工具。

传输：stdio（`dsflow mcp`，由 .mcp.json 或插件拉起）；平台 `dsflow ui` 另在 /mcp 提供 streamable HTTP。
工具的名字、参数、说明都来自登记表，和 `dsflow call`、`POST /api/tools/{name}` 完全一致。
需要可选依赖：`uv sync --extra mcp`。
"""

from __future__ import annotations

import functools
import inspect

from .core.project import ProjectError
from .core.rules import one_line
from .protocol import PROTOCOL_VERSION, REGISTRY, call

INSTRUCTIONS = (
    f"DSFlow Agent Protocol v{PROTOCOL_VERSION}。工作规矩：{one_line()}"
    "动手之前先调 next（它返回 tool_calls：下一步该调什么，environment 是分析环境的快检查，rules 是这几条规矩）；"
    "写文件用 file_write，讲解用 guide_put（自动核对与体检），执行 notebook 用 run_exec，"
    "提交审批 / 验收用 step_set_status，等用户在平台审批用 approval_wait（长轮询，pending 就再调）。"
    "所有工具返回同一信封 {ok, protocol, data | error}。工具不替用户改状态。"
)


def _mcp_tool(name: str):
    spec = REGISTRY[name]

    sig = inspect.signature(spec.fn)

    @functools.wraps(spec.fn)
    def inner(*args, **kwargs):
        bound = sig.bind_partial(*args, **kwargs)
        return call(name, dict(bound.arguments))

    # 参数签名照抄工具函数（MCP 由此生成输入 schema）；返回值永远是信封 dict，不能沿用工具函数的返回注解
    inner.__name__ = name
    inner.__doc__ = spec.description
    inner.__signature__ = sig.replace(return_annotation=dict)
    inner.__annotations__ = {**{k: v for k, v in spec.fn.__annotations__.items() if k != "return"}, "return": dict}
    return inner


def build_server():
    """需要 mcp 包（`uv sync --extra mcp`）。"""
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:  # pragma: no cover - 取决于环境
        raise ProjectError("没有安装 mcp 包：在 DSFlow 目录运行 uv sync --extra mcp") from exc

    server = MCPServer("dsflow", instructions=INSTRUCTIONS, version=PROTOCOL_VERSION)
    for name, spec in REGISTRY.items():
        server.tool(name=name, description=spec.description)(_mcp_tool(name))
    return server


def serve(transport: str = "stdio", **kwargs) -> None:
    build_server().run(transport, **kwargs)
