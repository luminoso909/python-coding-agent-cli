"""AI Coding Agent CLI —— 命令行程序入口。

使用 Typer 定义子命令，使用 Rich 负责彩色终端输出。
"""

import typer
from rich.console import Console
from rich.markup import escape

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


def main() -> None:
    """程序入口函数：把命令行参数交给 Typer 解析并分发到对应子命令。"""
    app()


if __name__ == "__main__":
    # 仅当作为脚本直接运行时才执行，被 import 时不会触发
    main()
