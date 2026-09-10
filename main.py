"""AI Coding Agent CLI —— 命令行程序入口。

使用 Typer 定义子命令，使用 Rich 负责彩色终端输出。
"""

import inspect

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from typer.models import CommandInfo

APP_NAME = "AI Coding Agent CLI"
VERSION = "0.1"

# 创建 Typer 应用对象，后续用 @app.command() 往它身上挂子命令
app = typer.Typer(help=f"{APP_NAME} v{VERSION}")

# Rich 的控制台对象，负责格式化输出（颜色、加粗等）
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


@app.command()
def hello(
    name: str = typer.Option(
        "Developer",
        "--name",
        "-n",
        help="要问候的名字",
        callback=_clean_name,  # Typer 在解析完参数后调用，用于校验/清洗
    ),
) -> None:
    """向指定用户打招呼（--name 可自定义名字）。"""
    show_banner()
    # escape() 把用户输入里的 [xxx] 转义成普通文本，避免被 Rich 当成样式标记解析
    console.print(f"Hello, {escape(name)}! Welcome to {APP_NAME}.")


@app.command()
def version() -> None:
    """输出版本号。"""
    console.print(f"{APP_NAME} v{VERSION}")


def _command_name(command_info: CommandInfo) -> str:
    """取命令名：装饰器显式指定时用它，否则退回函数名。"""
    return command_info.name or command_info.callback.__name__


def _command_summary(command_info: CommandInfo) -> str:
    """取一句话说明：优先用装饰器 help= 参数，否则用函数 docstring 的首行。"""
    text = command_info.help or inspect.cleandoc(command_info.callback.__doc__ or "")
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[0].strip() if lines else "（暂无说明）"


@app.command("help")  # 显式命名：函数名 help_command 避免遮蔽内置的 help()
def help_command() -> None:
    """显示所有可用命令及其说明。"""
    show_banner()
    # 直接读取 app 的命令注册表，新增子命令后这里会自动出现，不会漏写
    table = Table(title="可用命令", title_style="bold", header_style="bold cyan")
    table.add_column("命令", style="green", no_wrap=True)
    table.add_column("说明")
    for command_info in sorted(app.registered_commands, key=_command_name):
        if command_info.hidden:  # 被标记为隐藏的命令不展示
            continue
        table.add_row(_command_name(command_info), _command_summary(command_info))
    console.print(table)
    console.print("用 [bold]python main.py <命令> --help[/bold] 查看某个命令的详细用法。")


def main() -> None:
    """程序入口函数：把命令行参数交给 Typer 解析并分发到对应子命令。"""
    app()


if __name__ == "__main__":
    # 仅当作为脚本直接运行时才执行，被 import 时不会触发
    main()
