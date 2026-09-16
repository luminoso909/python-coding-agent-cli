"""Lab02 Prompt 2：验证 FileTool 的读写和行数统计。"""

from pathlib import Path

import pytest

from app.tools.file_tool import FileReadError, FileTool, FileWriteError


def test_read_text_file(tmp_path: Path) -> None:
    """普通文本读取返回正确的结构化字段。"""
    path = tmp_path / "a.txt"
    path.write_text("hello\nworld\n", encoding="utf-8")

    result = FileTool().read(path)

    assert result.path == str(path)
    assert result.content == "hello\nworld\n"
    assert result.encoding == "utf-8"
    assert result.size == 12
    assert result.line_count == 2


def test_read_nonexistent_raises(tmp_path: Path) -> None:
    """不存在的文件抛出读取异常。"""
    with pytest.raises(FileReadError, match="文件不存在"):
        FileTool().read(tmp_path / "missing.txt")


def test_read_directory_raises(tmp_path: Path) -> None:
    """读取目录抛出读取异常。"""
    with pytest.raises(FileReadError, match="不是普通文件"):
        FileTool().read(tmp_path)


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    """中文写读往返一致，字节数和新建标记正确。"""
    path = tmp_path / "out.txt"
    tool = FileTool()

    result = tool.write(path, "你好\n")

    assert result.path == str(path)
    assert result.bytes_written == 7
    assert result.created is True
    assert tool.read(path).content == "你好\n"


def test_write_overwrites_existing_file(tmp_path: Path) -> None:
    """默认覆盖已有文件，并将 created 标记为 False。"""
    path = tmp_path / "existing.txt"
    path.write_text("old content", encoding="utf-8")

    result = FileTool().write(path, "new")

    assert result.created is False
    assert result.bytes_written == 3
    assert path.read_text(encoding="utf-8") == "new"


def test_write_no_overwrite_raises(tmp_path: Path) -> None:
    """禁止覆盖时抛出写入异常，并保留原内容。"""
    path = tmp_path / "existing.txt"
    path.write_text("original", encoding="utf-8")

    with pytest.raises(FileWriteError, match="不允许覆盖"):
        FileTool().write(path, "replacement", overwrite=False)

    assert path.read_text(encoding="utf-8") == "original"


def test_write_creates_parent_dirs(tmp_path: Path) -> None:
    """写入深层路径时自动创建父目录。"""
    path = tmp_path / "a" / "b" / "c.txt"

    result = FileTool().write(path, "deep")

    assert result.created is True
    assert path.read_text(encoding="utf-8") == "deep"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", 0),
        ("single line", 1),
        ("single line\n", 1),
        ("a\nb\nc", 3),
        ("a\nb\nc\n", 3),
        ("\n", 1),
        ("a\n\n", 2),
    ],
)
def test_line_count(tmp_path: Path, text: str, expected: int) -> None:
    """批量验证空文件、末尾换行和空白行的行数统计。"""
    path = tmp_path / "lines.txt"
    path.write_text(text, encoding="utf-8")

    assert FileTool().read(path).line_count == expected
