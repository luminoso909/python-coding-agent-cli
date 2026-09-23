"""用 httpx 手写 Anthropic Messages 兼容客户端。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import httpx

Message = dict[str, Any]
ContentBlock = dict[str, Any]


class LLMError(RuntimeError):
    """网络、HTTP 状态或响应 JSON 解析失败。"""


class ProtocolError(LLMError):
    """模型响应不符合 Anthropic Messages 契约。"""


@dataclass(frozen=True)
class ProviderConfig:
    """一个 Anthropic 兼容服务商的连接配置。"""

    name: str
    url: str
    api_key_env: str
    model_env: str
    default_model: str | None = None


PROVIDERS: dict[str, ProviderConfig] = {
    "deepseek": ProviderConfig(
        name="DeepSeek",
        url="https://api.deepseek.com/anthropic/v1/messages",
        api_key_env="DEEPSEEK_API_KEY",
        model_env="DEEPSEEK_MODEL",
        default_model="deepseek-flash",
    ),
    "glm": ProviderConfig(
        name="GLM",
        url="https://open.bigmodel.cn/api/anthropic/v1/messages",
        api_key_env="GLM_API_KEY",
        model_env="GLM_MODEL",
    ),
}


def get_provider(name: str) -> ProviderConfig:
    """按命令行名称取得服务商配置。"""
    try:
        return PROVIDERS[name.lower()]
    except KeyError as error:
        choices = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"未知 provider: {name}；可选值: {choices}") from error


def _validate_content(content: object) -> list[ContentBlock]:
    if not isinstance(content, list):
        raise ProtocolError("assistant content 必须是内容块列表")

    result: list[ContentBlock] = []
    seen_ids: set[str] = set()
    for block in content:
        if not isinstance(block, dict):
            raise ProtocolError("每个 content block 必须是对象")
        block_type = block.get("type")
        if block_type == "text":
            if not isinstance(block.get("text"), str):
                raise ProtocolError("text block.text 必须是字符串")
        elif block_type == "tool_use":
            call_id = block.get("id")
            if not isinstance(call_id, str) or not call_id:
                raise ProtocolError("每个 tool_use 必须有非空 id")
            if call_id in seen_ids:
                raise ProtocolError(f"tool_use id 重复: {call_id}")
            seen_ids.add(call_id)
            if not isinstance(block.get("name"), str) or not block["name"]:
                raise ProtocolError("tool_use.name 必须是非空字符串")
            if not isinstance(block.get("input"), dict):
                raise ProtocolError("tool_use.input 必须是对象")
        elif block_type == "thinking":
            if not isinstance(block.get("thinking"), str):
                raise ProtocolError("thinking block.thinking 必须是字符串")
        else:
            raise ProtocolError(f"不支持的 content block 类型: {block_type!r}")
        result.append(deepcopy(block))
    return result


def validate_assistant_message(message: object) -> Message:
    """校验并复制一条可安全加入历史的 assistant 消息。"""
    if not isinstance(message, dict):
        raise ProtocolError("assistant message 必须是对象")
    if message.get("role") != "assistant":
        raise ProtocolError("响应 role 必须是 assistant")
    content = _validate_content(message.get("content"))
    tool_uses = [block for block in content if block["type"] == "tool_use"]
    text = "".join(
        block["text"] for block in content if block["type"] == "text"
    )
    if not tool_uses and not text.strip():
        raise ProtocolError("无工具调用时，assistant 文本不能为空")
    return {"role": "assistant", "content": content}


def text_content(message: Message) -> str:
    """合并 assistant 消息中的全部文本块。"""
    return "".join(
        block["text"]
        for block in message["content"]
        if block.get("type") == "text"
    )


class AnthropicClient:
    """以统一的 Anthropic Messages 格式调用 DeepSeek 或 GLM。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        provider: str,
        base_url: str | None = None,
        max_tokens: int = 2_048,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key 不能为空")
        if not model:
            raise ValueError("model 不能为空")
        if max_tokens < 1:
            raise ValueError("max_tokens 必须至少为 1")
        self.provider = get_provider(provider)
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or self.provider.url
        self.max_tokens = max_tokens
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def close(self) -> None:
        """关闭由当前对象创建的 HTTP Client。"""
        if self._owns_client:
            self._client.close()

    def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        system: str | None = None,
    ) -> Message:
        """发送一次 Messages 请求并返回标准化的 assistant 消息。"""
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = tools

        try:
            response = self._client.post(
                self.base_url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise LLMError(f"{self.provider.name} 请求超时") from error
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            raise LLMError(
                f"{self.provider.name} HTTP 请求失败（status={status}）"
            ) from error
        except httpx.RequestError as error:
            raise LLMError(f"{self.provider.name} 网络请求失败: {error}") from error

        try:
            body = response.json()
        except ValueError as error:
            raise LLMError(f"{self.provider.name} 响应不是合法 JSON") from error
        return self._parse_response(body)

    @staticmethod
    def _parse_response(body: object) -> Message:
        if not isinstance(body, dict):
            raise ProtocolError("响应顶层必须是对象")
        if body.get("type") != "message":
            raise ProtocolError("响应 type 必须是 message")

        message = validate_assistant_message(
            {"role": body.get("role"), "content": body.get("content")}
        )
        stop_reason = body.get("stop_reason")
        tool_uses = [
            block for block in message["content"] if block["type"] == "tool_use"
        ]
        if stop_reason == "tool_use":
            if not tool_uses:
                raise ProtocolError("stop_reason=tool_use 但没有 tool_use block")
        elif stop_reason in {"end_turn", "stop_sequence"}:
            if tool_uses:
                raise ProtocolError(
                    f"stop_reason={stop_reason} 但响应仍含 tool_use block"
                )
        else:
            raise ProtocolError(f"不支持的 stop_reason: {stop_reason!r}")
        return message
