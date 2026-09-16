"""验证 Lab02 FileTool 的文本、目录、编码与二进制处理能力。"""

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


def test_read_decode_error_is_wrapped(tmp_path: Path) -> None:
    """不合法的 UTF-8 字节抛出 FileReadError。"""
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(FileReadError, match="编码解码失败"):
        FileTool().read(path, encoding="utf-8")


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    """中文写读往返一致，字节数和新建标记正确。"""
    path = tmp_path / "out.txt"
    tool = FileTool()

    result = tool.write(path, "你好\n")

    assert result.path == str(path)
    assert result.bytes_written == 7
    assert result.created is True
    assert tool.read(path).content == "你好\n"
    assert path.read_bytes() == "你好\n".encode("utf-8")


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
        ("a\rb", 2),
        ("a\r\nb\r\n", 2),
    ],
)
def test_line_count(tmp_path: Path, text: str, expected: int) -> None:
    """批量验证空文件、末尾换行和空白行的行数统计。"""
    path = tmp_path / "lines.txt"
    path.write_text(text, encoding="utf-8")

    assert FileTool().read(path).line_count == expected


def test_list_dir_returns_sorted_entries(tmp_path: Path) -> None:
    """非递归列举返回排序稳定、元数据正确的目录项。"""
    (tmp_path / "z.txt").write_text("中文", encoding="utf-8")
    (tmp_path / "a").mkdir()

    entries = FileTool().list_dir(tmp_path)

    assert [entry.name for entry in entries] == ["a", "z.txt"]
    assert entries[0].is_dir is True
    assert entries[0].size == 0
    assert entries[1].is_dir is False
    assert entries[1].size == 6


def test_list_dir_recursive_pattern(tmp_path: Path) -> None:
    """递归模式只返回符合 pattern 的嵌套文件。"""
    nested = tmp_path / "src" / "tools"
    nested.mkdir(parents=True)
    (nested / "file_tool.py").write_text("pass\n", encoding="utf-8")
    (nested / "notes.txt").write_text("skip", encoding="utf-8")

    entries = FileTool().list_dir(tmp_path, recursive=True, pattern="*.py")

    assert [entry.name for entry in entries] == ["file_tool.py"]


def test_list_dir_non_recursive_pattern(tmp_path: Path) -> None:
    """非递归模式同样遵守 pattern。"""
    (tmp_path / "keep.py").write_text("pass", encoding="utf-8")
    (tmp_path / "skip.md").write_text("text", encoding="utf-8")

    entries = FileTool().list_dir(tmp_path, pattern="*.py")

    assert [entry.name for entry in entries] == ["keep.py"]


def test_list_dir_rejects_file(tmp_path: Path) -> None:
    """对普通文件列举目录时抛出 FileReadError。"""
    path = tmp_path / "plain.txt"
    path.write_text("text", encoding="utf-8")

    with pytest.raises(FileReadError, match="不是目录"):
        FileTool().list_dir(path)


def test_list_dir_rejects_missing_directory(tmp_path: Path) -> None:
    """不存在的目录抛出 FileReadError。"""
    with pytest.raises(FileReadError, match="目录不存在"):
        FileTool().list_dir(tmp_path / "missing")


def test_append_twice_and_read_lines(tmp_path: Path) -> None:
    """连续追加保持原内容，read_lines 去除各类换行符。"""
    path = tmp_path / "nested" / "log.txt"
    tool = FileTool()

    first = tool.append(path, "first\n")
    second = tool.append(path, "second\r\nthird")

    assert first.created is True
    assert second.created is False
    assert first.bytes_written == 6
    assert tool.read(path).content == "first\nsecond\r\nthird"
    assert tool.read_lines(path) == ["first", "second", "third"]
    assert path.read_bytes() == b"first\nsecond\r\nthird"


def test_read_detects_gbk_encoding(tmp_path: Path) -> None:
    """encoding=None 可以检测并正确解码 GBK 中文文件。"""
    path = tmp_path / "gbk.txt"
    expected = "这是一个用于测试编码检测的中文文件。"
    path.write_bytes(expected.encode("gbk"))

    result = FileTool().read(path, encoding=None)

    assert result.content == expected
    assert result.encoding.lower() in {"gbk", "gb2312", "gb18030"}
    assert result.size == len(expected.encode("gbk"))


def test_read_empty_file_with_auto_encoding(tmp_path: Path) -> None:
    """空文件无法检测编码时安全回退到 UTF-8。"""
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")

    result = FileTool().read(path, encoding=None)

    assert result.content == ""
    assert result.encoding == "utf-8"


def test_write_wraps_unknown_encoding(tmp_path: Path) -> None:
    """无效编码名被包装成 FileWriteError，不泄漏底层 LookupError。"""
    with pytest.raises(FileWriteError, match="写入失败"):
        FileTool().write(tmp_path / "bad.txt", "text", encoding="not-a-codec")


# ==================== Task 8 测试：二进制读写与上下文管理器 ====================


def test_binary_roundtrip(tmp_path: Path) -> None:
    """任意二进制数据写入后可以逐字节读回。"""
    path = tmp_path / "assets" / "sample.bin"
    data = bytes(range(256))
    tool = FileTool()

    result = tool.write_bytes(path, data)

    assert result.path == str(path)
    assert result.bytes_written == len(data)
    assert result.created is True
    assert tool.read_bytes(path) == data

    replacement = b"replacement"
    overwritten = tool.write_bytes(path, replacement)
    assert overwritten.created is False
    assert overwritten.bytes_written == len(replacement)
    assert tool.read_bytes(path) == replacement


def test_read_bytes_rejects_invalid_paths(tmp_path: Path) -> None:
    """二进制读取对缺失文件和目录使用统一的读取异常。"""
    tool = FileTool()

    with pytest.raises(FileReadError, match="文件不存在"):
        tool.read_bytes(tmp_path / "missing.bin")
    with pytest.raises(FileReadError, match="不是普通文件"):
        tool.read_bytes(tmp_path)


def test_batch_prints_boundaries_and_yields_tool(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """batch 输出开始和结束标记，并把当前 FileTool 交给 with 块。"""
    tool = FileTool()

    with tool.batch() as active_tool:
        assert active_tool is tool

    assert capsys.readouterr().out.splitlines() == ["批量开始", "批量结束"]


def test_batch_prints_end_when_operation_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """批处理中出现异常时仍执行 finally 并输出结束标记。"""
    tool = FileTool()

    with pytest.raises(RuntimeError, match="模拟失败"):
        with tool.batch():
            raise RuntimeError("模拟失败")

    assert capsys.readouterr().out.splitlines() == ["批量开始", "批量结束"]


# ========================== Task 8 测试结束 ==========================
