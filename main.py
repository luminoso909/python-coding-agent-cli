"""AI Coding Agent CLI 的唯一程序入口。"""

from __future__ import annotations

from getpass import getpass
import inspect
import json
import os
from pathlib import Path
from uuid import uuid4

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from typer.models import CommandInfo

from app.agent.react_agent import Agent
from app.llm.anthropic_client import (
    AnthropicClient,
    LLMError,
    Message,
    get_provider,
    text_content,
)
from app.llm.fake_client import FakeLLMClient
from app.tools.basic_tools import BasicTools

APP_NAME = "AI Coding Agent CLI"
VERSION = "0.2"

# 所有功能都注册到同一个 Typer 应用，由此保持统一的命令行入口。
app = typer.Typer(help=f"{APP_NAME} v{VERSION}")

# Rich 负责横幅、表格和错误信息等终端输出。
console = Console()


def show_banner() -> None:
    """打印程序名称与版本号横幅。"""
    console.print(f"[bold cyan]{APP_NAME} v{VERSION}[/bold cyan]")


def _clean_name(value: str) -> str:
    """去掉首尾空白，并拒绝空名字。"""
    name = value.strip()
    if not name:
        raise typer.BadParameter("名字不能为空")
    return name


def _make_client(
    provider_name: str,
    model_option: str | None,
    base_url: str | None,
) -> AnthropicClient:
    """从统一选项和厂商环境变量创建客户端。"""
    try:
        provider = get_provider(provider_name)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--provider") from error

    model = model_option or os.environ.get(provider.model_env) or provider.default_model
    if not model:
        raise typer.BadParameter(
            f"请用 --model 或环境变量 {provider.model_env} 指定模型",
            param_hint="--model",
        )
    api_key = os.environ.get(provider.api_key_env)
    if not api_key:
        api_key = getpass(f"{provider.name} API Key: ").strip()
    if not api_key:
        raise typer.BadParameter(
            f"请设置环境变量 {provider.api_key_env}",
            param_hint="--provider",
        )
    return AnthropicClient(
        api_key,
        model,
        provider=provider_name,
        base_url=base_url,
    )


def _fake_text(text: str) -> Message:
    """构造 Anthropic Messages 格式的 Fake 文本响应。"""
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def _fake_tool(call_id: str, name: str, values: dict[str, object]) -> Message:
    """构造只包含一个 tool_use 内容块的 Fake 响应。"""
    return {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": call_id, "name": name, "input": values}
        ],
    }


def _make_fake_client(
    report_name: str,
    binary_name: str,
    include_follow_up: bool,
) -> FakeLLMClient:
    """创建用于离线验证的确定性工具调用轨迹。"""
    responses = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call_list",
                    "name": "list_dir",
                    "input": {"path": "."},
                },
                {
                    "type": "tool_use",
                    "id": "call_read",
                    "name": "read_file",
                    "input": {"path": "notes.txt"},
                },
            ],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "我将依据读取结果写报告。"},
                {
                    "type": "tool_use",
                    "id": "call_write",
                    "name": "write_file",
                    "input": {
                        "path": report_name,
                        "content": (
                            "Fake 预设报告：工具结果必须回灌，"
                            "工具申请不等于执行。\n"
                        ),
                    },
                },
            ],
        },
        _fake_tool(
            "call_append",
            "append_file",
            {"path": report_name, "content": "追加写入验证完成。\n"},
        ),
        _fake_tool("call_lines", "read_lines", {"path": report_name}),
        _fake_tool(
            "call_write_bytes",
            "write_bytes",
            {"path": binary_name, "data_base64": "YWdlbnQtYmluYXJ5"},
        ),
        _fake_tool("call_read_bytes", "read_bytes", {"path": binary_name}),
        _fake_tool(
            "call_echo",
            "execute_command",
            {"command": "echo lab03-shell-ok"},
        ),
        _fake_text(f"Fake 工具调用轨迹完成；报告已写入 {report_name}。"),
    ]
    if include_follow_up:
        responses.extend(
            [
                _fake_tool(
                    "call_follow_up_read",
                    "read_file",
                    {"path": report_name},
                ),
                _fake_text(f"Fake 追问已回读并复核 {report_name}。"),
            ]
        )
    return FakeLLMClient(responses)


@app.command()
def hello(
    name: str = typer.Option(
        "Developer",
        "--name",
        "-n",
        help="要问候的名字",
        # Typer 解析参数后调用，用于去除空白并拒绝空名字。
        callback=_clean_name,
    ),
) -> None:
    """向指定用户打招呼（--name 可自定义名字）。"""
    show_banner()
    # 避免用户输入被 Rich 当成样式标记解析。
    console.print(f"Hello, {escape(name)}! Welcome to {APP_NAME}.")


@app.command()
def version() -> None:
    """输出版本号。"""
    console.print(f"{APP_NAME} v{VERSION}")


@app.command()
def chat(
    prompt: str = typer.Argument(..., help="普通对话内容"),
    provider: str = typer.Option("deepseek", help="deepseek 或 glm"),
    model: str | None = typer.Option(None, help="模型名；默认读取厂商环境变量"),
    base_url: str | None = typer.Option(
        None,
        help="完整的 /v1/messages 地址；用于覆盖默认端点",
    ),
) -> None:
    """通过 Anthropic Messages 兼容接口进行一次普通对话。"""
    client = _make_client(provider, model, base_url)
    try:
        message = client.chat([{"role": "user", "content": prompt}])
        console.print(text_content(message))
    except LLMError as error:
        console.print(f"[red]{escape(str(error))}[/red]")
        raise typer.Exit(1) from error
    finally:
        client.close()


@app.command()
def agent(
    prompt: str = typer.Argument(..., help="需要 Agent 实际完成的任务"),
    provider: str = typer.Option("deepseek", help="deepseek 或 glm"),
    model: str | None = typer.Option(None, help="模型名；默认读取厂商环境变量"),
    base_url: str | None = typer.Option(
        None,
        help="完整的 /v1/messages 地址；用于覆盖默认端点",
    ),
    root: Path = typer.Option(Path("test_path"), help="工具允许访问的根目录"),
    max_iterations: int = typer.Option(8, min=1, help="一次任务最多请求模型的次数"),
    follow_up: str | None = typer.Option(None, help="首个任务结束后的同会话追问"),
    trace: bool = typer.Option(False, help="输出完整 Anthropic 消息历史"),
    fake: bool = typer.Option(
        False,
        "--fake",
        help="使用确定性 Fake 响应离线执行工具调用轨迹",
    ),
) -> None:
    """运行可列目录、读写文件和执行固定命令的最小 ReAct Agent。"""
    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        raise typer.BadParameter(f"目录不存在: {resolved_root}", param_hint="--root")

    if fake:
        artifact_id = uuid4().hex[:8]
        report_name = f"report-fake-{artifact_id}.txt"
        binary_name = f"payload-fake-{artifact_id}.bin"
        client = _make_fake_client(
            report_name,
            binary_name,
            include_follow_up=follow_up is not None,
        )
    else:
        client = _make_client(provider, model, base_url)
    runner = Agent(
        client,
        BasicTools(resolved_root),
        max_iterations=max_iterations,
    )
    try:
        result = runner.run(prompt)
        mode = "FAKE" if fake else "LIVE"
        console.print(f"{mode} {result.status} / iterations={result.iterations}")
        console.print(result.content)
        if follow_up and result.status == "completed":
            result = runner.run(follow_up)
            console.print(f"follow-up {result.status} / iterations={result.iterations}")
            console.print(result.content)
        if trace:
            for index, message in enumerate(runner.messages, start=1):
                console.print(
                    f"[{index}] "
                    + json.dumps(message, ensure_ascii=False, separators=(",", ":"))
                )
        if result.status != "completed":
            raise typer.Exit(1)
    finally:
        client.close()


def _command_name(command_info: CommandInfo) -> str:
    """取得 Typer 命令的显示名称。"""
    return command_info.name or command_info.callback.__name__


def _command_summary(command_info: CommandInfo) -> str:
    """取得命令 docstring 的第一条非空行。"""
    text = command_info.help or inspect.cleandoc(command_info.callback.__doc__ or "")
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[0].strip() if lines else "（暂无说明）"


@app.command("help")
def help_command() -> None:
    """显示所有可用命令及其说明。"""
    show_banner()
    table = Table(title="可用命令", title_style="bold", header_style="bold cyan")
    table.add_column("命令", style="green", no_wrap=True)
    table.add_column("说明")
    # 动态读取命令注册表，新增命令后无需维护硬编码清单。
    for command_info in sorted(app.registered_commands, key=_command_name):
        if not command_info.hidden:
            table.add_row(_command_name(command_info), _command_summary(command_info))
    console.print(table)
    console.print("用 [bold]python main.py <命令> --help[/bold] 查看详细用法。")


def main() -> None:
    """唯一入口：把命令行参数交给 Typer 分发。"""
    app()


if __name__ == "__main__":
    # 被其他模块 import 时不会启动 CLI。
    main()
