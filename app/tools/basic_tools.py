"""把 Lab02 FileTool 适配成四个可供 Agent 调用的工具。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any, Callable

from app.tools.file_tool import FileTool, FileToolError

ToolResult = dict[str, Any]


class BasicTools:
    """限制在指定根目录和固定命令内的四工具执行器。"""

    MAX_ENTRIES = 100
    MAX_OUTPUT_CHARS = 4_000
    COMMAND_TIMEOUT = 5.0
    ECHO_COMMAND = "echo lab03-shell-ok"

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
        """返回 Anthropic Messages 格式的四份工具 Schema。"""
        command_values = sorted(self.allowed_commands)
        return [
            self._schema(
                "read_file",
                "读取教学目录中的 UTF-8 文本文件",
                {"path": {"type": "string", "description": "相对文件路径"}},
                ["path"],
            ),
            self._schema(
                "write_file",
                "新建 UTF-8 文本文件；不覆盖已有文件",
                {
                    "path": {"type": "string", "description": "相对文件路径"},
                    "content": {"type": "string", "description": "写入内容"},
                },
                ["path", "content"],
            ),
            self._schema(
                "list_dir",
                "列出教学目录下指定目录的一层内容",
                {"path": {"type": "string", "description": "相对目录路径"}},
                ["path"],
            ),
            self._schema(
                "execute_command",
                "在教学目录执行一条固定白名单命令",
                {
                    "command": {
                        "type": "string",
                        "enum": command_values,
                        "description": "必须完整匹配白名单",
                    }
                },
                ["command"],
            ),
        ]

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
            raise ValueError("命令不在 Lab03 固定白名单中")
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
        contracts: dict[str, tuple[dict[str, type], Callable[..., ToolResult]]] = {
            "read_file": ({"path": str}, self.read_file),
            "write_file": ({"path": str, "content": str}, self.write_file),
            "list_dir": ({"path": str}, self.list_dir),
            "execute_command": ({"command": str}, self.execute_command),
        }
        if name not in contracts:
            return {"ok": False, "error": f"未知工具: {name}"}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "工具 input 必须是对象"}
        values = arguments

        fields, function = contracts[name]
        if set(values) != set(fields):
            return {
                "ok": False,
                "error": f"参数字段必须恰好为: {sorted(fields)}",
            }
        invalid = [key for key, expected in fields.items() if not isinstance(values[key], expected)]
        if invalid:
            return {"ok": False, "error": f"参数类型错误: {sorted(invalid)}"}
        try:
            return function(**values)
        except (FileToolError, ValueError) as error:
            return {"ok": False, "error": str(error)}
