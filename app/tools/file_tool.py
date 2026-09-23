"""为 AI Coding Agent 提供带异常防护的文本文件读写能力。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

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
            path: 待读取文件的路径。
            encoding: 文件的字符编码；传入 None 时自动检测。

        Raises:
            FileReadError: 路径不存在、不是文件、解码失败或读取失败。
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
            path: 目标文件路径。
            content: 要写入的文本。
            encoding: 文件的字符编码，默认为 UTF-8。
            overwrite: 是否允许覆盖已有文件。

        Raises:
            FileWriteError: 禁止覆盖已有文件或写入失败。
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
            bytes_written=bytes_written,        # 写入的字符（按照编码后字符计算）的数量（不是字节数量）
            created=created,                    # 是否新创建（新建 or 覆盖）
        )

    def list_dir(
        self,
        path: str | Path,
        recursive: bool = False,
        pattern: str = "*",
    ) -> list[DirEntry]:
        """按稳定顺序返回目录项，可选择递归并按名称模式筛选。"""
        target = Path(path)
        self._require_directory(target)

        try:
            if recursive:
                children = list(target.rglob(pattern))
            else:
                children = [
                    child for child in target.iterdir() if child.match(pattern)
                ]

            entries: list[DirEntry] = []
            for child in sorted(children, key=lambda item: item.as_posix()):
                is_dir = child.is_dir()
                size = 0 if is_dir else child.stat().st_size
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
        """在文件末尾追加文本，不存在时创建文件及其父目录。"""
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
        return self.read(path, encoding=encoding).content.splitlines()

    # ==================== Task 8：二进制读写与上下文管理器 ====================
    # Step 13 的实现从这里开始，便于在实验报告和代码审查中快速定位。

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
    def batch(self) -> Iterator[FileTool]:
        """标记一组批量文件操作，并保证结束信息一定输出。"""
        print("批量开始")
        try:
            yield self
        finally:
            print("批量结束")

    # ========================== Task 8 实现结束 ==========================
