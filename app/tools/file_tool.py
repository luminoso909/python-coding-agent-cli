"""为 AI Coding Agent 提供带异常防护的文本文件读写能力。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Generator

import chardet


class FileToolError(Exception):
    """FileTool 所有异常的基类。"""


class FileReadError(FileToolError):
    """文件读取失败。"""


class FileWriteError(FileToolError):
    """文件写入失败。"""


@dataclass
class FileContent:
    """文件读取结果。"""

    path: str
    content: str
    encoding: str
    size: int
    line_count: int


@dataclass
class WriteResult:
    """文件写入结果。"""

    path: str
    bytes_written: int
    created: bool


@dataclass
class DirEntry:
    """目录中的一个文件或子目录。"""

    name: str
    path: str
    is_dir: bool
    size: int


class FileTool:
    """为 Agent 提供文本文件读写能力。"""

    # 定义两个异常检查：分别检查文件和目录存在与否、状态
    # 下面的 target 是 pathlib.Path 对象，所以可以调用 .exists() | .is_file() | .is_dir() 方法来判断
    @staticmethod
    def _require_file(target: Path) -> None:
        """确认路径指向普通文件，并包装路径检查产生的系统异常。"""
        try:
            if not target.exists():
                raise FileReadError(f"文件不存在: {target}")
            if not target.is_file():
                raise FileReadError(f"不是普通文件: {target}")
        except OSError as error:
            raise FileReadError(f"检查文件失败: {error}") from error

    @staticmethod
    def _require_directory(target: Path) -> None:
        """确认路径指向目录，并包装路径检查产生的系统异常。"""
        try:
            if not target.exists():
                raise FileReadError(f"目录不存在: {target}")
            if not target.is_dir():
                raise FileReadError(f"不是目录: {target}")
        except OSError as error:
            raise FileReadError(f"检查目录失败: {error}") from error

    def read(
        self,
        path: str | Path,
        encoding: str | None = "utf-8",
    ) -> FileContent:
        """读取文本文件并返回结构化结果。

        Args:
            path: 待读取文件的路径（str 或 Path）。
            encoding: 解码使用的编码，默认 "utf-8"。
                - 传字符串：用指定编码解码
                - 传 None：调用 chardet 自动检测编码

        Returns:
            FileContent: 结构化读取结果，字段为：
                - path: 实际读取的路径字符串
                - content: 解码后的文本（str）
                - encoding: 实际用于解码的编码名
                - size: 磁盘上的原始字节数
                - line_count: 逻辑行数（按 splitlines() 统计）

        Raises:
            FileReadError: 以下情况统一抛出：
                - 路径不存在（"文件不存在: ..."）
                - 路径不是普通文件（"不是普通文件: ..."）
                - 编码名无效（LookupError）
                - 字节无法用指定编码解码（UnicodeDecodeError）
                - 读取字节时发生系统错误（OSError）
        """
        target = Path(path)

        # 判断路径异常性，然后文件判断编码方式并解码，如果编码输入错误则报错
        self._require_file(target)
        try:
            raw_content = target.read_bytes()
            actual_encoding = encoding or self._detect_encoding(raw_content)
            content = raw_content.decode(actual_encoding)
        except (UnicodeDecodeError, LookupError) as error:
            raise FileReadError(
                f"编码解码失败（encoding={actual_encoding}），请检查文件编码: {error}"
            ) from error
        except OSError as error:
            raise FileReadError(f"读取失败: {error}") from error

        # 文件分行输出列表，并 return
        line_count = len(content.splitlines())

        return FileContent(
            path=str(target),
            content=content,
            encoding=actual_encoding,
            size=len(raw_content),
            line_count=line_count,
        )

    @staticmethod
    def _detect_encoding(data: bytes) -> str:
        """检测字节数据的编码，无法确定时回退到 UTF-8。"""
        if not data:
            return "utf-8"

        try:
            detected = chardet.detect(data).get("encoding")     # 检测字符类型，返回字典类似 {"encoding":str|None, "confidence":float, "language":str|None}
        except (TypeError, ValueError):
            detected = None
        return detected or "utf-8"

    def write(
        self,
        path: str | Path,
        content: str,
        encoding: str = "utf-8",
        overwrite: bool = True,
    ) -> WriteResult:
        """写入文本文件并返回结构化结果。

        Args:
            path: 目标文件路径（str 或 Path）。
            content: 要写入的文本。
            encoding: 写入使用的编码，默认 "utf-8"。
            overwrite: 是否允许覆盖已有文件，默认 True。
                - True：文件已存在则覆盖
                - False：文件已存在则抛 FileWriteError

        Returns:
            WriteResult: 结构化写入结果，字段为：
                - path: 目标文件路径字符串
                - bytes_written: 按 encoding 编码后写入的字节数
                - created: 调用前文件是否不存在（True=新建，False=覆盖）

        Raises:
            FileWriteError: 以下情况统一抛出：
                - 检查目标文件是否存在时出错（OSError）
                - 文件已存在且 overwrite=False
                - 编码名无效（LookupError）
                - 内容无法用指定编码表示（UnicodeError）
                - 创建父目录或写入文件失败（OSError）
        """
        target = Path(path)

        # 判断目标文件是否存在、是否可写
        try:
            target_exists = target.exists()
        except OSError as error:
            raise FileWriteError(f"检查目标文件失败: {error}") from error

        if target_exists and not overwrite:
            raise FileWriteError(f"文件已存在且不允许覆盖: {target}")

        created = not target_exists
        try:
            bytes_written = len(content.encode(encoding))
            target.parent.mkdir(parents=True, exist_ok=True)        # 这个主要是针对新建文件并写入的情况，新建文件时可以顺手把 dir 也一并建立
            target.write_text(content, encoding=encoding, newline="")
            # newline 表示不做任何换行符（如多加 ‘\r’）转换，写入什么就是什么
        except (OSError, UnicodeError, LookupError) as error:
            raise FileWriteError(f"写入失败: {error}") from error

        return WriteResult(
            path=str(target),
            bytes_written=bytes_written,        # 按指定编码后实际写入的字节数量
            created=created,                    # 是否新创建（新建或覆盖）
        )

    def list_dir(
        self,
        path: str | Path,
        recursive: bool = False,
        pattern: str = "*",
    ) -> list[DirEntry]:
        """按稳定顺序返回目录项，可选择递归并按名称模式筛选。

        Args:
            path: 待列举的目录路径。
            recursive: 是否递归进入子目录（是否列出当前目录下存在的文件夹下的内容），默认为 False。
            pattern: 文件名匹配模式（glob 语法），默认为 "*"，表示匹配所有项。举例 pattern="*.py"：只匹配扩展名为 .py 的文件。

        Returns:
            list[DirEntry]: 按路径稳定排序的目录项列表。
                每个 DirEntry 包含：
                - name: 文件或目录名（不含父路径）
                - path: 完整路径字符串
                - is_dir: 是否为目录
                - size: 文件字节数；目录固定为 0

        Raises:
            FileReadError: 目录不存在、不是目录，或列举过程中发生系统错误。
        """
        target = Path(path)
        self._require_directory(target)

        try:
            if recursive:
                children = list(target.rglob(pattern))      # target.rglob()：从 target 开始递归遍历所有子目录，返回匹配 pattern 的路径。
            else:
                children = [child for child in target.iterdir() if child.match(pattern)]        # target.iterdir()：只列出直接子项（文件 + 子目录），不进入子目录。

            entries: list[DirEntry] = []
            for child in sorted(children, key=lambda item: item.as_posix()):    # item.as_posix() 返回的是一个用 / 分隔的路径字符串，作为 key 则会按这些字符串的字典序排列。
                is_dir = child.is_dir()
                size = 0 if is_dir else child.stat().st_size    # 如果是目录，size 记为 0。如果是文件，child.stat().st_size 取字节数
                entries.append(
                    DirEntry(
                        name=child.name,
                        path=str(child),
                        is_dir=is_dir,
                        size=size,
                    )
                )
        except OSError as error:
            raise FileReadError(f"列举目录失败: {error}") from error

        return entries

    def append(
        self,
        path: str | Path,
        content: str,
        encoding: str = "utf-8",
    ) -> WriteResult:
        """在文件末尾追加文本，不存在时创建文件及其父目录。

        Args:
            path: 目标文件路径（str 或 Path）。
            content: 要追加的文本。
            encoding: 写入使用的编码，默认 "utf-8"。

        Returns:
            WriteResult: 结构化写入结果，字段为：
                - path: 目标文件路径字符串
                - bytes_written: 按 encoding 编码后实际追加的字节数
                - created: 调用前文件是否不存在（True=新建，False=已存在追加）

        Raises:
            FileWriteError: 以下情况统一抛出：
                - 路径检查失败（OSError，如权限问题）
                - 编码名无效（LookupError，如 "not-a-codec"）
                - 内容无法用指定编码表示（UnicodeError）
                - 创建父目录或打开/写入文件失败（OSError）
        """
        target = Path(path)

        try:
            created = not target.exists()
            bytes_written = len(content.encode(encoding))
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding=encoding, newline="") as file:
                file.write(content)
        except (OSError, UnicodeError, LookupError) as error:
            raise FileWriteError(f"追加失败: {error}") from error

        return WriteResult(
            path=str(target),
            bytes_written=bytes_written,
            created=created,
        )

    def read_lines(
        self,
        path: str | Path,
        encoding: str | None = "utf-8",
    ) -> list[str]:
        """读取文本并返回不包含换行符的行列表。"""
        return self.read(path, encoding=encoding).content.splitlines()      # 直接对 content(str 格式) 使用 .splitlines() 方法


    # ==================== 二进制读写与批量操作上下文 ====================

    def read_bytes(self, path: str | Path) -> bytes:
        """读取二进制文件；路径错误和系统错误统一包装为 FileReadError。"""
        target = Path(path)
        self._require_file(target)

        try:
            return target.read_bytes()
        except OSError as error:
            raise FileReadError(f"二进制读取失败: {error}") from error

    def write_bytes(self, path: str | Path, data: bytes) -> WriteResult:
        """写入二进制数据，自动创建父目录并返回写入结果。"""
        target = Path(path)

        try:
            created = not target.exists()
            target.parent.mkdir(parents=True, exist_ok=True)
            bytes_written = target.write_bytes(data)
        except OSError as error:
            raise FileWriteError(f"二进制写入失败: {error}") from error

        return WriteResult(
            path=str(target),
            bytes_written=bytes_written,
            created=created,
        )

    @contextmanager
    def batch(self) -> Generator[FileTool, None, None]:
        """标记一组批量文件操作，并保证结束信息一定输出。"""
        print("批量开始")
        try:
            yield self
        finally:
            print("批量结束")

    # ==================== 二进制读写与批量操作结束 ====================
