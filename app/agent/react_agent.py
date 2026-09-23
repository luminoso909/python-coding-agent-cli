"""保存 Anthropic Messages 历史并执行最小 ReAct 闭环。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.llm.anthropic_client import (
    LLMError,
    Message,
    text_content,
    validate_assistant_message,
)
from app.tools.basic_tools import BasicTools


class ChatClient(Protocol):
    def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        system: str | None = None,
    ) -> Message:
        """向聊天模型发送消息并获取下一条助手消息。

        Args:
            messages: Anthropic Messages 格式的历史消息列表，按时间顺序排列。
            tools: 可选的工具 schema 列表；传入 None 时不向模型暴露工具。
            system: 可选的 system prompt，用于约束模型行为。

        Raises:
            LLMError: 具体客户端调用失败、响应无效或无法解析时可能抛出。

        Results:
            Message: 模型返回的助手消息，应包含 content 等字段。
        """
        ...


@dataclass
class AgentResult:
    status: str
    content: str
    iterations: int


class Agent:
    """由模型选择动作，由 Python 执行工具并回灌 Observation。"""

    DEFAULT_SYSTEM_PROMPT = (
        "你是课程文件 Agent。只能通过提供的工具了解和修改教学目录；"
        "必须根据真实工具结果回答，不能把计划当作已经执行。"
    )

    def __init__(
        self,
        client: ChatClient,
        tools: BasicTools,
        *,
        max_iterations: int = 8,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        """初始化 Agent。

        Args:
            client: 聊天客户端，需实现 ChatClient.chat。
            tools: 基础工具集，提供 schemas 和 dispatch。
            max_iterations: 最大模型请求轮数，必须大于等于 1。
            system_prompt: 传给模型的 system prompt。

        Raises:
            ValueError: max_iterations 小于 1。

        Results:
            None: 构造函数无返回值。
        """
        if max_iterations < 1:
            raise ValueError("max_iterations 必须至少为 1")
        self.client = client
        self.tools = tools
        self.max_iterations = max_iterations
        self.system_prompt = system_prompt
        self.messages: list[Message] = []

    def run(self, user_text: str) -> AgentResult:
        """执行最小 ReAct 闭环，并保存 Anthropic Messages 历史。

        Args:
            user_text: 用户输入文本，不能为空或仅含空白。

        Raises:
            ValueError: user_text 不是字符串，或为空、仅含空白。

        Results:
            AgentResult: 运行结果。
                status: 结束状态，可能为 "completed"、"error" 或 "iteration_limit"。
                content: 结束时的文本内容；completed 时为助手文本，error 时为错误信息，iteration_limit 时为限制说明。
                iterations: 实际执行的模型请求轮数。

        副作用:
            会向 self.messages 追加 user、assistant 和 tool_result 消息。
            LLMError 不会向上抛出，而是被转换为 status="error" 的 AgentResult。
        """
        if not isinstance(user_text, str) or not user_text.strip():
            raise ValueError("user_text 不能为空")
        self.messages.append({"role": "user", "content": user_text})

        for iteration in range(1, self.max_iterations + 1):
            try:
                response = self.client.chat(
                    self.messages,
                    self.tools.schemas,
                    system=self.system_prompt,
                )
                assistant = validate_assistant_message(response)
            except LLMError as error:
                return AgentResult("error", str(error), iteration)

            self.messages.append(assistant)
            calls = [
                block
                for block in assistant["content"]
                if block["type"] == "tool_use"
            ]
            if not calls:
                return AgentResult("completed", text_content(assistant), iteration)

            observations: list[dict[str, Any]] = []
            for call in calls:
                observation = self.tools.dispatch(call["name"], call["input"])
                observations.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": json.dumps(
                            observation, ensure_ascii=False, separators=(",", ":")
                        ),
                        "is_error": not observation.get("ok", False),
                    }
                )
            self.messages.append({"role": "user", "content": observations})

        return AgentResult(
            "iteration_limit",
            f"达到最大模型请求次数 {self.max_iterations}，任务未正常结束",
            self.max_iterations,
        )
