#!/usr/bin/env python3
"""init_project.py —— 项目脚手架脚本。

运行后自动创建本实验所需的目录结构，并为 Python 包目录补上空的 ``__init__.py``。

设计原则：

- **幂等**：重复运行不会报错，也不会重复创建。
- **安全**：已存在的文件绝不覆盖，脚本只"补齐缺失的部分"。
- **零依赖**：只用标准库，在 ``pip install -r requirements.txt`` 之前也能运行。
"""

from pathlib import Path

# __file__ 是本脚本自身的路径，resolve() 取绝对路径，parent 取所在目录
# 用 __file__ 而不是 os.getcwd()，因此在任何目录下执行都能正确定位项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent

# 需要 __init__.py 的目录：它们会被 Python 当作"包"，可用 import 导入
PACKAGE_DIRS: tuple[str, ...] = (
    "app",
    "app/agent",
    "app/cli",
    "app/core",
    "app/llm",
    "app/tools",
    "tests",
)

# 普通目录：只放文档等资源，不需要 __init__.py
PLAIN_DIRS: tuple[str, ...] = ("docs",)


def create_directory(path: Path) -> bool:
    """创建目录（含缺失的父目录）。

    ``exist_ok=True`` 表示目录已存在时静默通过、不抛异常，这正是幂等的关键。
    返回 True 表示本次确实新建了目录，False 表示它本来就存在。
    """
    is_new = not path.is_dir()
    path.mkdir(parents=True, exist_ok=True)
    return is_new


def create_init_file(path: Path) -> bool:
    """创建空的 ``__init__.py``；若文件已存在则原样保留（绝不覆盖已有代码）。

    返回 True 表示本次新建了文件，False 表示已存在、跳过。
    """
    if path.exists():
        return False
    path.touch()  # 创建空文件
    return True


def scaffold(root: Path) -> tuple[int, int]:
    """按清单创建目录与 ``__init__.py``，返回 (新建目录数, 新建文件数)。"""
    new_dirs = 0
    new_files = 0

    for relative in PLAIN_DIRS:
        directory = root / relative
        if create_directory(directory):
            print(f"  [新建目录] {relative}/")
            new_dirs += 1
        else:
            print(f"  [已存在]   {relative}/")

    for relative in PACKAGE_DIRS:
        directory = root / relative
        if create_directory(directory):
            print(f"  [新建目录] {relative}/")
            new_dirs += 1
        else:
            print(f"  [已存在]   {relative}/")

        init_file = directory / "__init__.py"
        if create_init_file(init_file):
            print(f"  [新建文件] {(Path(relative) / '__init__.py').as_posix()}")
            new_files += 1
        else:
            print(f"  [已存在]   {(Path(relative) / '__init__.py').as_posix()}")

    return new_dirs, new_files


def main() -> None:
    """脚本入口：打印进度并在结束时给出小结。"""
    print(f"项目根目录: {PROJECT_ROOT}")
    print("开始检查目录结构 ...")

    new_dirs, new_files = scaffold(PROJECT_ROOT)

    print(f"完成：新建目录 {new_dirs} 个，新建文件 {new_files} 个。")
    if new_dirs == 0 and new_files == 0:
        print("目录结构已完整，无需改动。")


if __name__ == "__main__":
    main()
