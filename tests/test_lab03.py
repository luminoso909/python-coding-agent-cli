"""验证 Anthropic HTTP 契约、工具边界和最小 ReAct 闭环。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from app.agent.react_agent import Agent
from app.llm.anthropic_client import (
    AnthropicClient,
    LLMError,
    Message,
    ProtocolError,
    get_provider,
)
from app.llm.fake_client import FakeLLMClient
from app.tools.basic_tools import BasicTools
from app.tools.file_tool import FileTool
from main import app as cli_app


def text_message(text: str) -> Message:
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def tool_use(call_id: str, name: str, values: object) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": values}


def assistant_call(
    call_id: str,
    name: str,
    values: object,
    text: str | None = None,
) -> Message:
    content: list[dict[str, Any]] = []
    if text is not None:
        content.append({"type": "text", "text": text})
    content.append(tool_use(call_id, name, values))
    return {"role": "assistant", "content": content}


def api_response(content: list[dict[str, Any]], stop_reason: str) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": content,
        "stop_reason": stop_reason,
    }


def make_http_client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_provider_registry_integrates_deepseek_and_glm() -> None:
    deepseek = get_provider("deepseek")
    glm = get_provider("glm")
    assert deepseek.url == "https://api.deepseek.com/anthropic/v1/messages"
    assert deepseek.api_key_env == "DEEPSEEK_API_KEY"
    assert glm.url == "https://open.bigmodel.cn/api/anthropic/v1/messages"
    assert glm.api_key_env == "GLM_API_KEY"


def test_fake_records_deep_copy_of_request() -> None:
    messages = [{"role": "user", "content": "修改前"}]
    fake = FakeLLMClient([text_message("回答")])
    fake.chat(messages, system="系统说明")
    messages[0]["content"] = "修改后"
    messages.append({"role": "user", "content": "后来追加"})
    assert fake.requests[0] == {
        "messages": [{"role": "user", "content": "修改前"}],
        "tools": None,
        "system": "系统说明",
    }


@pytest.mark.parametrize("provider", ["deepseek", "glm"])
def test_anthropic_client_plain_chat_builds_unified_request(provider: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == httpx.URL("https://provider.test/v1/messages")
        assert request.headers["x-api-key"] == "secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert payload == {
            "model": "model-test",
            "max_tokens": 321,
            "messages": [{"role": "user", "content": "你好"}],
            "system": "只回答事实",
        }
        return httpx.Response(
            200,
            json=api_response([{"type": "text", "text": "你好"}], "end_turn"),
        )

    transport = make_http_client(handler)
    client = AnthropicClient(
        "secret",
        "model-test",
        provider=provider,
        base_url="https://provider.test/v1/messages",
        max_tokens=321,
        http_client=transport,
    )
    assert client.chat(
        [{"role": "user", "content": "你好"}], system="只回答事实"
    )["content"][0]["text"] == "你好"
    transport.close()


def test_anthropic_client_sends_tools_and_parses_input_as_object() -> None:
    call = tool_use("call_1", "read_file", {"path": "notes.txt"})

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tools"][0]["name"] == "read_file"
        assert "stream" not in payload
        return httpx.Response(200, json=api_response([call], "tool_use"))

    transport = make_http_client(handler)
    client = AnthropicClient(
        "secret", "model-test", provider="deepseek", http_client=transport
    )
    message = client.chat(
        [],
        [{"name": "read_file", "input_schema": {"type": "object"}}],
    )
    assert message["content"][0]["input"] == {"path": "notes.txt"}
    transport.close()


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_anthropic_client_wraps_http_status(status: int) -> None:
    transport = make_http_client(
        lambda request: httpx.Response(status, json={"error": "details"})
    )
    client = AnthropicClient(
        "secret", "model-test", provider="glm", http_client=transport
    )
    with pytest.raises(LLMError, match=f"status={status}"):
        client.chat([])
    transport.close()


def test_anthropic_client_wraps_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    transport = make_http_client(handler)
    client = AnthropicClient(
        "secret", "model-test", provider="deepseek", http_client=transport
    )
    with pytest.raises(LLMError, match="超时"):
        client.chat([])
    transport.close()


def test_anthropic_client_rejects_non_json_response() -> None:
    transport = make_http_client(lambda request: httpx.Response(200, text="not-json"))
    client = AnthropicClient(
        "secret", "model-test", provider="glm", http_client=transport
    )
    with pytest.raises(LLMError, match="合法 JSON"):
        client.chat([])
    transport.close()


@pytest.mark.parametrize(
    "body, message",
    [
        ({}, "type"),
        (api_response([], "end_turn"), "不能为空"),
        (api_response([{"type": "text", "text": 7}], "end_turn"), "字符串"),
        (api_response([{"type": "unknown"}], "end_turn"), "不支持的 content block"),
        (api_response([{"type": "text", "text": "x"}], "max_tokens"), "stop_reason"),
        (api_response([tool_use("call", "read_file", {})], "end_turn"), "仍含 tool_use"),
    ],
)
def test_anthropic_client_rejects_invalid_protocol(
    body: dict[str, Any], message: str
) -> None:
    transport = make_http_client(lambda request: httpx.Response(200, json=body))
    client = AnthropicClient(
        "secret", "model-test", provider="glm", http_client=transport
    )
    with pytest.raises(ProtocolError, match=message):
        client.chat([])
    transport.close()


@pytest.mark.parametrize(
    "content, message",
    [
        ([tool_use("", "read_file", {})], "非空 id"),
        (
            [
                tool_use("same", "read_file", {"path": "a.txt"}),
                tool_use("same", "read_file", {"path": "b.txt"}),
            ],
            "id 重复",
        ),
        ([tool_use("one", "read_file", "not-object")], "input 必须是对象"),
    ],
)
def test_anthropic_client_rejects_invalid_tool_use(
    content: list[dict[str, Any]], message: str
) -> None:
    body = api_response(content, "tool_use")
    transport = make_http_client(lambda request: httpx.Response(200, json=body))
    client = AnthropicClient(
        "secret", "model-test", provider="deepseek", http_client=transport
    )
    with pytest.raises(ProtocolError, match=message):
        client.chat([])
    transport.close()


def test_schemas_use_anthropic_input_schema(tmp_path: Path) -> None:
    schemas = BasicTools(tmp_path).schemas
    assert [item["name"] for item in schemas] == [
        "read_file",
        "write_file",
        "list_dir",
        "execute_command",
        "append_file",
        "read_lines",
        "read_bytes",
        "write_bytes",
    ]
    assert all(
        item["input_schema"]["additionalProperties"] is False for item in schemas
    )
    assert all("function" not in item for item in schemas)


def test_every_file_tool_operation_has_a_registered_adapter(tmp_path: Path) -> None:
    public_operations = {
        name
        for name, value in vars(FileTool).items()
        if not name.startswith("_") and callable(value)
    }
    assert public_operations == set(BasicTools.FILE_METHOD_ADAPTERS) | {"batch"}

    schema_names = {item["name"] for item in BasicTools(tmp_path).schemas}
    assert set(BasicTools.FILE_METHOD_ADAPTERS.values()) <= schema_names


def test_dispatch_reuses_file_tool_with_decoded_input(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("中文说明\n", encoding="utf-8")
    result = BasicTools(tmp_path).dispatch("read_file", {"path": "notes.txt"})
    assert result["ok"] is True
    assert result["content"] == "中文说明\n"
    assert result["line_count"] == 1


def test_append_and_read_lines_are_registered(tmp_path: Path) -> None:
    tools = BasicTools(tmp_path)
    first = tools.dispatch(
        "append_file", {"path": "journal.txt", "content": "first\n"}
    )
    second = tools.dispatch(
        "append_file", {"path": "journal.txt", "content": "second\n"}
    )
    lines = tools.dispatch("read_lines", {"path": "journal.txt"})

    assert first["ok"] is True and first["created"] is True
    assert second["ok"] is True and second["created"] is False
    assert lines == {
        "ok": True,
        "path": "journal.txt",
        "lines": ["first", "second"],
        "line_count": 2,
    }


def test_binary_tools_use_base64_for_json_transport(tmp_path: Path) -> None:
    tools = BasicTools(tmp_path)
    written = tools.dispatch(
        "write_bytes",
        {"path": "payload.bin", "data_base64": "AP+AQUdFTlQ="},
    )
    read = tools.dispatch("read_bytes", {"path": "payload.bin"})

    assert written == {
        "ok": True,
        "path": "payload.bin",
        "bytes_written": 8,
        "created": True,
    }
    assert read == {
        "ok": True,
        "path": "payload.bin",
        "data_base64": "AP+AQUdFTlQ=",
        "bytes_read": 8,
    }


def test_write_bytes_rejects_invalid_base64(tmp_path: Path) -> None:
    result = BasicTools(tmp_path).dispatch(
        "write_bytes",
        {"path": "payload.bin", "data_base64": "not base64!"},
    )
    assert result["ok"] is False
    assert "Base64" in result["error"]
    assert not (tmp_path / "payload.bin").exists()


@pytest.mark.parametrize(
    "name, arguments, error",
    [
        ("missing", {}, "未知工具"),
        ("read_file", "not-object", "必须是对象"),
        ("read_file", {}, "参数字段"),
        ("read_file", {"path": "x", "extra": 1}, "参数字段"),
        ("read_file", {"path": 17}, "参数类型"),
    ],
)
def test_dispatch_rejects_invalid_tools(
    name: str, arguments: object, error: str, tmp_path: Path
) -> None:
    result = BasicTools(tmp_path).dispatch(name, arguments)
    assert result["ok"] is False
    assert error in result["error"]


@pytest.mark.parametrize("path", ["../outside.txt", "/tmp/outside.txt"])
def test_tools_reject_paths_outside_root(path: str, tmp_path: Path) -> None:
    result = BasicTools(tmp_path).dispatch(
        "write_file", {"path": path, "content": "blocked"}
    )
    assert result["ok"] is False
    assert "路径" in result["error"]


def test_write_file_never_overwrites_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "report.txt"
    target.write_text("original", encoding="utf-8")
    result = BasicTools(tmp_path).dispatch(
        "write_file", {"path": "report.txt", "content": "replacement"}
    )
    assert result["ok"] is False
    assert target.read_text(encoding="utf-8") == "original"


def test_list_dir_returns_sorted_entries_and_truncation(tmp_path: Path) -> None:
    for name in ["b.txt", "a.txt", "c.txt"]:
        (tmp_path / name).write_text(name, encoding="utf-8")
    tools = BasicTools(tmp_path)
    tools.MAX_ENTRIES = 2
    result = tools.dispatch("list_dir", {"path": "."})
    assert [entry["name"] for entry in result["entries"]] == ["a.txt", "b.txt"]
    assert result["truncated"] is True


def test_execute_command_allows_exact_echo(tmp_path: Path) -> None:
    result = BasicTools(tmp_path).dispatch(
        "execute_command", {"command": "echo lab03-shell-ok"}
    )
    assert result["ok"] is True
    assert result["stdout"].strip() == "lab03-shell-ok"
    assert result["returncode"] == 0


def test_execute_command_rejects_expansion_without_starting_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("非法命令不应启动进程")

    monkeypatch.setattr(subprocess, "run", forbidden)
    result = BasicTools(tmp_path).dispatch(
        "execute_command", {"command": "echo lab03-shell-ok && pwd"}
    )
    assert result["ok"] is False
    assert "白名单" in result["error"]


def test_execute_command_timeout_is_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(args[0], timeout=5, output=b"partial")

    monkeypatch.setattr(subprocess, "run", timeout)
    result = BasicTools(tmp_path).dispatch(
        "execute_command", {"command": "echo lab03-shell-ok"}
    )
    assert result == {
        "ok": False,
        "stdout": "partial",
        "stderr": "",
        "returncode": None,
        "timed_out": True,
        "truncated": False,
    }


def four_tool_responses(report_name: str = "report.txt") -> list[Message]:
    return [
        assistant_call("list_1", "list_dir", {"path": "."}),
        assistant_call("read_1", "read_file", {"path": "notes.txt"}),
        assistant_call(
            "write_1", "write_file",
            {"path": report_name, "content": "根据说明生成的报告\n"},
            text="准备写报告",
        ),
        assistant_call(
            "echo_1", "execute_command", {"command": "echo lab03-shell-ok"}
        ),
        text_message("四个工具均已根据 Observation 完成。"),
    ]


def result_block(message: Message, index: int = 0) -> dict[str, Any]:
    return message["content"][index]


def result_json(message: Message, index: int = 0) -> dict[str, Any]:
    return json.loads(result_block(message, index)["content"])


def test_fake_four_tool_trajectory_creates_file_and_backfeeds_every_result(
    tmp_path: Path,
) -> None:
    (tmp_path / "notes.txt").write_text("真实说明内容\n", encoding="utf-8")
    fake = FakeLLMClient(four_tool_responses())
    agent = Agent(fake, BasicTools(tmp_path), max_iterations=5)
    result = agent.run("完成四工具任务")

    assert result.status == "completed"
    assert result.iterations == 5
    assert (tmp_path / "report.txt").read_text(encoding="utf-8") == "根据说明生成的报告\n"
    assert len(fake.requests) == 5
    assert [message["role"] for message in fake.requests[0]["messages"]] == ["user"]
    assert fake.requests[0]["system"] == Agent.DEFAULT_SYSTEM_PROMPT

    expected_ids = ["list_1", "read_1", "write_1", "echo_1"]
    for request_number, expected_id in enumerate(expected_ids, start=2):
        messages = fake.requests[request_number - 1]["messages"]
        assistant = messages[-2]
        observation_message = messages[-1]
        assert [assistant["role"], observation_message["role"]] == ["assistant", "user"]
        observation = result_block(observation_message)
        call = next(
            block for block in assistant["content"] if block["type"] == "tool_use"
        )
        assert observation["type"] == "tool_result"
        assert observation["tool_use_id"] == call["id"] == expected_id
        assert json.loads(observation["content"])["ok"] is True

    assert any(
        entry["name"] == "notes.txt"
        for entry in result_json(fake.requests[1]["messages"][-1])["entries"]
    )
    assert result_json(fake.requests[2]["messages"][-1])["content"] == "真实说明内容\n"
    assert result_json(fake.requests[4]["messages"][-1])["stdout"].strip() == "lab03-shell-ok"


def test_mixed_text_and_tool_use_does_not_finish_early(tmp_path: Path) -> None:
    fake = FakeLLMClient([
        assistant_call(
            "write_1", "write_file", {"path": "a.txt", "content": "data"},
            text="我现在写文件",
        ),
        text_message("写入完成"),
    ])
    result = Agent(fake, BasicTools(tmp_path), max_iterations=2).run("写文件")
    assert result.status == "completed"
    assert result.iterations == 2
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "data"


def test_multiple_calls_execute_in_returned_order(tmp_path: Path) -> None:
    calls: Message = {
        "role": "assistant",
        "content": [
            tool_use("write", "write_file", {"path": "ordered.txt", "content": "ready"}),
            tool_use("read", "read_file", {"path": "ordered.txt"}),
        ],
    }
    fake = FakeLLMClient([calls, text_message("完成")])
    agent = Agent(fake, BasicTools(tmp_path), max_iterations=2)
    assert agent.run("先写后读").status == "completed"
    second_request_tail = fake.requests[1]["messages"][-2:]
    assert [message["role"] for message in second_request_tail] == ["assistant", "user"]
    observations = second_request_tail[1]["content"]
    assert [item["tool_use_id"] for item in observations] == ["write", "read"]
    assert [item["tool_use_id"] for item in observations] == [
        call["id"] for call in second_request_tail[0]["content"]
    ]
    assert json.loads(observations[1]["content"])["content"] == "ready"


def test_iteration_limit_executes_last_calls_without_extra_request(tmp_path: Path) -> None:
    fake = FakeLLMClient([
        assistant_call("one", "list_dir", {"path": "."}),
        assistant_call("two", "list_dir", {"path": "."}),
        text_message("不应被消费"),
    ])
    agent = Agent(fake, BasicTools(tmp_path), max_iterations=2)
    result = agent.run("持续调用")
    assert result.status == "iteration_limit"
    assert result.iterations == 2
    assert len(fake.requests) == 2
    assert fake.remaining_responses == 1
    assert result_block(agent.messages[-1])["tool_use_id"] == "two"


def test_follow_up_keeps_previous_history_and_resets_iteration_count(tmp_path: Path) -> None:
    fake = FakeLLMClient([text_message("第一问回答"), text_message("追问回答")])
    agent = Agent(fake, BasicTools(tmp_path), max_iterations=1)
    assert agent.run("第一问").iterations == 1
    second = agent.run("追问")
    assert second.status == "completed"
    assert second.iterations == 1
    roles = [message["role"] for message in fake.requests[1]["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert fake.requests[1]["messages"][-2]["content"][0]["text"] == "第一问回答"


def test_agent_stops_on_invalid_fake_response(tmp_path: Path) -> None:
    fake = FakeLLMClient([{"role": "assistant", "content": []}])
    result = Agent(fake, BasicTools(tmp_path)).run("任务")
    assert result.status == "error"
    assert "不能为空" in result.content


def test_observation_is_backfed_before_second_request(tmp_path: Path) -> None:
    """工具成功后，下一次请求必须已有对应的 tool_result。"""
    fake = FakeLLMClient([
        assistant_call(
            "write_report", "write_file",
            {"path": "report.txt", "content": "实际写入结果"},
        ),
        text_message("已根据写入结果回答。"),
    ])
    agent = Agent(fake, BasicTools(tmp_path), max_iterations=2)
    result = agent.run("写报告")

    assert result.status == "completed"
    assert (tmp_path / "report.txt").read_text(encoding="utf-8") == "实际写入结果"
    second_messages = fake.requests[1]["messages"]
    assert [message["role"] for message in second_messages] == ["user", "assistant", "user"]
    assistant = second_messages[-2]
    observation = result_block(second_messages[-1])
    assert observation["tool_use_id"] == assistant["content"][0]["id"]
    assert json.loads(observation["content"])["bytes_written"] == 18


def test_tool_failure_is_backfed_as_error_result(tmp_path: Path) -> None:
    fake = FakeLLMClient([
        assistant_call("missing", "read_file", {"path": "missing.txt"}),
        text_message("已根据失败结果停止读取。"),
    ])
    result = Agent(fake, BasicTools(tmp_path), max_iterations=2).run("读取缺失文件")
    observation = result_block(fake.requests[1]["messages"][-1])
    assert result.status == "completed"
    assert observation["is_error"] is True
    assert json.loads(observation["content"])["ok"] is False
    assert "文件不存在" in json.loads(observation["content"])["error"]


def test_single_entry_fake_demo_executes_registered_file_tools(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("真实说明内容\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli_app,
        [
            "agent",
            "完成工具调用任务",
            "--fake",
            "--root",
            str(tmp_path),
            "--follow-up",
            "请回读报告并复核",
            "--trace",
        ],
    )

    assert result.exit_code == 0
    assert "FAKE completed / iterations=8" in result.output
    assert "follow-up completed / iterations=2" in result.output
    assert "call_list" in result.output
    assert "call_read" in result.output
    assert "call_write" in result.output
    assert "call_append" in result.output
    assert "call_lines" in result.output
    assert "call_write_bytes" in result.output
    assert "call_read_bytes" in result.output
    assert "call_echo" in result.output
    assert "call_follow_up_read" in result.output
    reports = list(tmp_path.glob("report-fake-*.txt"))
    assert len(reports) == 1
    assert "工具结果必须回灌" in reports[0].read_text(encoding="utf-8")
    assert "追加写入验证完成" in reports[0].read_text(encoding="utf-8")
    payloads = list(tmp_path.glob("payload-fake-*.bin"))
    assert len(payloads) == 1
    assert payloads[0].read_bytes() == b"agent-binary"
