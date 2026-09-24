"""用于离线验证 Anthropic Messages Agent 控制流的确定性 Fake Client。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.llm.anthropic_client import Message


class FakeLLMClient:
    """依次返回预设响应，并保存每次请求当时的深拷贝。"""

    def __init__(self, responses: list[Message]) -> None:
        self._responses = deepcopy(responses)
        self.requests: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        system: str | None = None,
    ) -> Message:
        self.requests.append(
            {
                "messages": deepcopy(messages),
                "tools": deepcopy(tools),
                "system": system,
            }
        )
        if not self._responses:
            raise RuntimeError("FakeLLMClient 没有剩余响应")
        return deepcopy(self._responses.pop(0))

    def close(self) -> None:
        """保持与真实客户端一致的关闭接口；Fake 没有网络资源。"""

    @property
    def remaining_responses(self) -> int:
        return len(self._responses)
