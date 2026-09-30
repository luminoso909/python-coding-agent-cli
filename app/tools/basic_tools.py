"""把 FileTool 适配成可供 Agent 调用的受限工具集。"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Any, Callable

from app.tools.file_tool import FileTool, FileToolError

ToolResult = dict[str, Any]


@dataclass(frozen=True)
class ToolContract:
    """一项 Agent 工具的 Schema、参数类型和执行函数。"""

    description: str
    properties: dict[str, dict[str, Any]]
    argument_types: dict[str, type]
    handler: Callable[..., ToolResult]


class BasicTools:
    """限制在指定根目录和固定命令内的 Agent 工具执行器。"""

    MAX_ENTRIES = 100
    MAX_OUTPUT_CHARS = 4_000
    COMMAND_TIMEOUT = 5.0
    ECHO_COMMAND = "echo lab03-shell-ok"
    FILE_METHOD_ADAPTERS = {
        "read": "read_file",
        "write": "write_file",
        "list_dir": "list_dir",
        "append": "append_file",
        "read_lines": "read_lines",
        "read_bytes": "read_bytes",
        "write_bytes": "write_bytes",
    }

    def __init__(self, root: str | Path, file_tool: FileTool | None = None) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"工具根目录不存在或不是目录: {self.root}")
        self.file_tool = file_tool or FileTool()

    @property
    def allowed_commands(self) -> set[str]:
        platform_command = "cd" if os.name == "nt" else "pwd"
        return {self.ECHO_COMMAND, platform_command}

    @property
    def schemas(self) -> list[dict[str, Any]]:
        """返回 Anthropic Messages 格式的工具 Schema 列表。"""
        return [
            self._schema(
                name,
                contract.description,
                contract.properties,
                list(contract.argument_types),
            )
            for name, contract in self._contracts().items()
        ]

    def _contracts(self) -> dict[str, ToolContract]:
        """集中登记 Schema、参数约束与执行函数。"""
        path_property = {"type": "string", "description": "相对文件路径"}
        content_property = {"type": "string", "description": "文本内容"}
        return {
            "read_file": ToolContract(
                "读取工作目录中的 UTF-8 文本文件",
                {"path": path_property},
                {"path": str},
                self.read_file,
            ),
            "write_file": ToolContract(
                "新建 UTF-8 文本文件；不覆盖已有文件",
                {"path": path_property, "content": content_property},
                {"path": str, "content": str},
                self.write_file,
            ),
            "list_dir": ToolContract(
                "列出工作目录下指定目录的一层内容",
                {"path": {"type": "string", "description": "相对目录路径"}},
                {"path": str},
                self.list_dir,
            ),
            "execute_command": ToolContract(
                "在工作目录执行一条固定白名单命令",
                {
                    "command": {
                        "type": "string",
                        "enum": sorted(self.allowed_commands),
                        "description": "必须完整匹配白名单",
                    }
                },
                {"command": str},
                self.execute_command,
            ),
            "append_file": ToolContract(
                "在已有 UTF-8 文本文件末尾追加内容；文件不存在时创建",
                {"path": path_property, "content": content_property},
                {"path": str, "content": str},
                self.append_file,
            ),
            "read_lines": ToolContract(
                "按行读取 UTF-8 文本文件，返回不含换行符的字符串列表",
                {"path": path_property},
                {"path": str},
                self.read_lines,
            ),
            "read_bytes": ToolContract(
                "读取二进制文件，并以 Base64 字符串返回内容",
                {"path": path_property},
                {"path": str},
                self.read_bytes,
            ),
            "write_bytes": ToolContract(
                "把 Base64 字符串解码后写入二进制文件",
                {
                    "path": path_property,
                    "data_base64": {
                        "type": "string",
                        "description": "使用标准 Base64 编码的二进制内容",
                    },
                },
                {"path": str, "data_base64": str},
                self.write_bytes,
            ),
        }

    @staticmethod
    def _schema(
        name: str,
        description: str,
        properties: dict[str, Any],
        required: list[str],
    ) -> dict[str, Any]:
        return {
            "name": name,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        }

    def _resolve(self, relative_path: str) -> Path:
        raw = Path(relative_path)
        if raw.is_absolute():
            raise ValueError("只允许相对路径")
        target = (self.root / raw).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("路径不能超出工具根目录")
        return target

    def read_file(self, path: str) -> ToolResult:
        result = self.file_tool.read(self._resolve(path), encoding="utf-8")
        return {
            "ok": True,
            "path": str(Path(result.path).relative_to(self.root)),
            "content": result.content,
            "encoding": result.encoding,
            "size": result.size,
            "line_count": result.line_count,
        }

    def write_file(self, path: str, content: str) -> ToolResult:
        result = self.file_tool.write(
            self._resolve(path), content, encoding="utf-8", overwrite=False
        )
        return {
            "ok": True,
            "path": str(Path(result.path).relative_to(self.root)),
            "bytes_written": result.bytes_written,
            "created": result.created,
        }

    def append_file(self, path: str, content: str) -> ToolResult:
        result = self.file_tool.append(
            self._resolve(path), content, encoding="utf-8"
        )
        return {
            "ok": True,
            "path": str(Path(result.path).relative_to(self.root)),
            "bytes_appended": result.bytes_written,
            "created": result.created,
        }

    def read_lines(self, path: str) -> ToolResult:
        target = self._resolve(path)
        lines = self.file_tool.read_lines(target, encoding="utf-8")
        return {
            "ok": True,
            "path": str(target.relative_to(self.root)),
            "lines": lines,
            "line_count": len(lines),
        }

    def read_bytes(self, path: str) -> ToolResult:
        target = self._resolve(path)
        data = self.file_tool.read_bytes(target)
        return {
            "ok": True,
            "path": str(target.relative_to(self.root)),
            "data_base64": base64.b64encode(data).decode("ascii"),
            "bytes_read": len(data),
        }

    def write_bytes(self, path: str, data_base64: str) -> ToolResult:
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("data_base64 不是合法的标准 Base64 字符串") from error
        result = self.file_tool.write_bytes(self._resolve(path), data)
        return {
            "ok": True,
            "path": str(Path(result.path).relative_to(self.root)),
            "bytes_written": result.bytes_written,
            "created": result.created,
        }

    def list_dir(self, path: str) -> ToolResult:
        entries = self.file_tool.list_dir(self._resolve(path))
        shown = entries[: self.MAX_ENTRIES]
        return {
            "ok": True,
            "entries": [
                {
                    "name": entry.name,
                    "path": str(Path(entry.path).relative_to(self.root)),
                    "is_dir": entry.is_dir,
                    "size": entry.size,
                }
                for entry in shown
            ],
            "truncated": len(entries) > len(shown),
        }

    def execute_command(self, command: str) -> ToolResult:
        if command not in self.allowed_commands:
            raise ValueError("命令不在固定白名单中")
        argv = (
            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", command]
            if os.name == "nt"
            else ["/bin/sh", "-c", command]
        )
        try:
            completed = subprocess.run(
                argv,
                cwd=self.root,
                capture_output=True,
                timeout=self.COMMAND_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            stdout = self._decode_output(error.stdout)
            stderr = self._decode_output(error.stderr)
            stdout, stdout_cut = self._truncate(stdout)
            stderr, stderr_cut = self._truncate(stderr)
            return {
                "ok": False,
                "stdout": stdout,
                "stderr": stderr,
                "returncode": None,
                "timed_out": True,
                "truncated": stdout_cut or stderr_cut,
            }
        except OSError as error:
            return {"ok": False, "error": f"命令启动失败: {error}"}

        stdout, stdout_cut = self._truncate(self._decode_output(completed.stdout))
        stderr, stderr_cut = self._truncate(self._decode_output(completed.stderr))
        return {
            "ok": completed.returncode == 0,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": completed.returncode,
            "timed_out": False,
            "truncated": stdout_cut or stderr_cut,
        }

    @staticmethod
    def _decode_output(value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _truncate(self, value: str) -> tuple[str, bool]:
        if len(value) <= self.MAX_OUTPUT_CHARS:
            return value, False
        return value[: self.MAX_OUTPUT_CHARS], True

    def dispatch(self, name: str, arguments: object) -> ToolResult:
        """严格校验 Anthropic tool_use.input，再调用白名单方法。"""
        contracts = self._contracts()
        if name not in contracts:
            return {"ok": False, "error": f"未知工具: {name}"}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "工具 input 必须是对象"}
        values = arguments

        contract = contracts[name]
        fields = contract.argument_types
        if set(values) != set(fields):
            return {
                "ok": False,
                "error": f"参数字段必须恰好为: {sorted(fields)}",
            }
        invalid = [key for key, expected in fields.items() if not isinstance(values[key], expected)]
        if invalid:
            return {"ok": False, "error": f"参数类型错误: {sorted(invalid)}"}
        try:
            return contract.handler(**values)
        except (FileToolError, ValueError) as error:
            return {"ok": False, "error": str(error)}
