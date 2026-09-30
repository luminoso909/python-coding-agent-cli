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


@dataclass(frozen=True)         # frozen = True：保证属性的值全局不可变（防止被更改）；且能保证该 dataclass 可哈希
class ProviderConfig:
    """一个 Anthropic 兼容服务商的连接配置。

    用于描述“如何连接某个服务商、如何认证、用哪个模型”。
    创建后不可修改（frozen=True）。

    Attributes:
        name: 服务商的人类可读名称，用于错误信息和日志。
        url: Anthropic Messages 端点地址，客户端向此地址发送 POST 请求。
        api_key_env: 存放 API Key 的环境变量名（不是 Key 本身）。
        model_env: 存放模型名的环境变量名（不是模型名本身）。
        default_model: 用户未通过环境变量指定模型时的兜底模型名；
            为 None 表示该服务商没有默认模型，必须由用户显式指定。

    Raises:
        FrozenInstanceError: 尝试修改任何字段时抛出（frozen=True 的效果）。
    """

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
        choices = ", ".join(sorted(PROVIDERS))      # sorted(dict) 是直接对字典的 key 进行字典序的排序
        raise ValueError(f"未知 provider: {name}；可选值: {choices}") from error


def _validate_content(content: object) -> list[ContentBlock]:
    '''校验一个 Anthropic 响应的 content 字段是不是合法的内容块列表，并返回一份深拷贝（防止对话历史被修改）。'''
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
            if not isinstance(call_id, str) or not call_id:     # 检查工具编号 id
                raise ProtocolError("每个 tool_use 必须有非空 id")
            if call_id in seen_ids:                             # 要求工具编号不能重复（保证 llm 知道这次吊用对应的是哪次调用、过程和结果如何）
                raise ProtocolError(f"tool_use id 重复: {call_id}")
            seen_ids.add(call_id)                               # 检查工具名称
            if not isinstance(block.get("name"), str) or not block["name"]:
                raise ProtocolError("tool_use.name 必须是非空字符串")
            if not isinstance(block.get("input"), dict):        # 检查 input 类型为 dict
                raise ProtocolError("tool_use.input 必须是对象")
            
        elif block_type == "thinking":
            if not isinstance(block.get("thinking"), str):
                raise ProtocolError("thinking block.thinking 必须是字符串")
            
        else:
            raise ProtocolError(f"不支持的 content block 类型: {block_type!r}")
        
        result.append(deepcopy(block))      # 深拷贝：递归复制所有层级，新对象和原对象完全独立；浅拷贝：只复制最外层容器，内部的元素仍然是共享的引用
    return result


def validate_assistant_message(message: object) -> Message:
    """校验并复制一条可安全加入历史的 assistant 消息。"""
    if not isinstance(message, dict):
        raise ProtocolError("assistant message 必须是对象")
    if message.get("role") != "assistant":
        raise ProtocolError("响应 role 必须是 assistant")
    
    content = _validate_content(message.get("content"))
    tool_uses = [block for block in content if block["type"] == "tool_use"]
    text = "".join(block["text"] for block in content if block["type"] == "text")
    if not tool_uses and not text.strip():          # 用 text.strip() 保证也不会出现类似 "  " 这样的纯空白字符
        raise ProtocolError("无工具调用时，assistant 文本不能为空")
    return {"role": "assistant", "content": content}


def text_content(message: Message) -> str:
    """合并 assistant 消息中的全部文本块。"""
    return "".join(block["text"] for block in message["content"] if block.get("type") == "text")


class AnthropicClient:
    """以统一的 Anthropic Messages 格式调用 DeepSeek 或 GLM。

    作用：
    构造请求：把 messages、tools、system 打包成 Anthropic Messages 格式的 JSON；
    发 HTTP 请求：用 httpx POST 到服务商端点；
    解析响应：把返回的 JSON 校验成标准 Message。
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        *,              # * 表示下面的参数必须用关键字传递，避免位置参数顺序混乱。
        provider: str,
        base_url: str | None = None,
        max_tokens: int = 2048,
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
        """关闭由当前对象创建的 HTTP Client（如果 http_client 是外部传入的，close() 什么都不做）。"""
        if self._owns_client:
            self._client.close()

    def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        system: str | None = None,
    ) -> Message:
        """发送一次 Messages 请求，并返回标准化的 assistant 消息。

        Args:
            messages: Anthropic Messages 格式的对话历史，按时间顺序排列。
            tools: 可选的工具 schema 列表；传 None 时不向模型暴露工具。
            system: 可选的 system prompt，用于约束模型行为。

        Returns:
            Message: 校验后的标准 assistant 消息，可安全加入历史。

        Raises:
            LLMError: 请求超时、HTTP 状态错误、网络错误或响应不是合法 JSON。
            ProtocolError: 响应结构不符合 Anthropic Messages 契约。
        """
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
            """response 句的作用
            发送请求：把 payload 序列化成 JSON，附上 headers，发到 self.base_url；
            等待响应：接收服务端返回的 HTTP 响应；
            返回 Response 对象：把响应封装成 httpx.Response 赋给 response。
            """
            response = self._client.post(
                self.base_url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },      # headers 基本只需要修改 self.api_key，其他两项写法固定
                json=payload,
            )
            response.raise_for_status()

        except httpx.TimeoutException as error:
            raise LLMError(f"{self.provider.name} 请求超时") from error
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            raise LLMError(f"{self.provider.name} HTTP 请求失败（status={status}）") from error
        except httpx.RequestError as error:
            raise LLMError(f"{self.provider.name} 网络请求失败: {error}") from error

        try:
            body = response.json()          # 解析 json 格式，失败则报错
        except ValueError as error:
            raise LLMError(f"{self.provider.name} 响应不是合法 JSON") from error
        return self._parse_response(body)

    @staticmethod
    def _parse_response(body: object) -> Message:
        """校验 HTTP 响应体并返回标准 assistant 消息。

        Args:
            body: response.json() 的结果，类型未知，运行时校验。

        Returns:
            Message: 深拷贝后的标准 assistant 消息。

        Raises:
            ProtocolError: 顶层不是对象、type 不是 message、content 结构非法、stop_reason 与 tool_use 不一致等。
        """
        if not isinstance(body, dict):
            raise ProtocolError("响应顶层必须是对象")
        if body.get("type") != "message":
            raise ProtocolError("响应 type 必须是 message")

        message = validate_assistant_message({"role": body.get("role"), "content": body.get("content")})
        stop_reason = body.get("stop_reason")
        tool_uses = [block for block in message["content"] if block["type"] == "tool_use"]

        if stop_reason == "tool_use":
            if not tool_uses:
                raise ProtocolError("stop_reason=tool_use 但没有 tool_use block")
        elif stop_reason in {"end_turn", "stop_sequence"}:
            if tool_uses:
                raise ProtocolError(f"stop_reason={stop_reason} 但响应仍含 tool_use block")
        else:
            raise ProtocolError(f"不支持的 stop_reason: {stop_reason!r}")
        return message
