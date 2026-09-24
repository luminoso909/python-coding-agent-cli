## 一、审查目标与结论

### 1. 本轮任务

本轮使用可复用的 `app.llm.fake_client.FakeLLMClient`、真实临时文件工具和 `httpx.MockTransport` 审查 Anthropic Messages 版 Agent 契约，全程没有调用真实模型 API：

- assistant 的 `tool_use` 必须先进入历史，随后才出现对应的 user `tool_result`；
- `tool_use_id` 必须与 `tool_use.id` 配对；
- 同一响应中的多个工具按模型返回顺序执行，并合并进紧随其后的一个 user 消息；
- `text` 与 `tool_use` 同时存在时仍应执行工具；
- 无工具调用且没有非空文本时必须停止并报告协议错误；
- `MAX_ITERATIONS` 只限制一次 `run()` 的模型请求次数，不允许额外请求总结；
- 用户追问继续使用原会话历史，但本次迭代计数重新开始。

上述契约已由 Fake 与 HTTP Mock 覆盖。恢复 Lab01 脚手架并补充单入口 Fake 演示后，完整项目当前为 77 项测试通过。

## 二、测试场景及其能发现的错误

### 1. HTTP Mock 测试

| 测试范围 | 主要断言 | 能发现的错误 |
| --- | --- | --- |
| DeepSeek 与 GLM 统一请求 | 两个 provider 都发送 `model`、`max_tokens`、`messages`，使用 `x-api-key` 与 `anthropic-version` | 厂商分支产生不同消息格式、认证头缺失、请求字段遗漏 |
| 普通对话 | 不需要工具时不发送 `tools`，解析 `text` 内容块 | 普通对话误带工具、只支持 Tool Calling、不解析内容块 |
| 工具响应 | 发送 `name`、`description`、`input_schema`；解析 `tool_use.input` 对象 | 仍发送 OpenAI 的 `function.parameters`、把 Anthropic input 当 JSON 字符串 |
| HTTP 错误 | 400、401、429、500 转换为 `LLMError` | HTTP 失败被误当作模型回答 |
| 网络和正文错误 | 超时与非 JSON 正文转换为明确错误 | 网络异常泄漏、只检查状态码 |
| 协议错误 | 检查 `type`、`role`、内容块、`stop_reason`、工具 ID 与 input | 把损坏、截断或不受支持的响应加入会话历史 |

HTTP Mock 只验证本地请求构造和解析逻辑，不证明真实账号、模型名、套餐或网络可用。

### 2. Fake 与真实临时工具测试

| 测试范围 | 主要断言 | 能发现的错误 |
| --- | --- | --- |
| Fake 请求快照 | 原消息修改后，已经保存的请求保持不变 | Fake 保存引用或浅拷贝，旧快照被后续历史污染 |
| 四工具轨迹 | 五次请求；真实文件产物；每轮 `assistant → user(tool_result)`；ID 与真实结果匹配 | 工具实际执行但结果没回灌、角色顺序或配对错误 |
| 多工具响应 | 先写后读；两个结果按原顺序放入同一个 user 内容数组 | 调用被重排、并发后乱序、只执行第一个调用 |
| 文本和工具并存 | 有文本时仍写文件并继续下一轮 | 看到文本就提前返回，导致工具未执行 |
| 空响应 | 空内容返回 error | 把空响应当成功 |
| 迭代上限 | 不多请求一次；最后一轮工具仍执行并保留 Observation | off-by-one、多请求总结、丢失最后结果 |
| 追问历史 | 保留前一问答；本次 iterations 从 1 重新计数 | 丢失历史或把会话总轮数当作本次上限 |
| 工具失败 | `is_error=true`，结构化失败内容进入下一次请求 | 工具失败直接终止，或错误只打印到终端 |

## 三、回灌缺陷的失败到修复记录

### 1. AI 提出的可验证原因

故障是“终端有结果，但第二次请求没有工具消息”。本地文件已经生成，说明 Acting 已完成，因此优先检查 Observation 到会话历史的连接：结果可能没有在下一次 `client.chat()` 前追加，或者被追加到了临时列表。

验证方法同时检查真实文件和 Fake 的第二次请求。若文件存在，而请求末尾没有与 `tool_use.id` 对应的 `tool_result.tool_use_id`，就能把故障定位到回灌步骤。

### 2. 修改前的故障注入

临时移除 Agent 中追加 Observation 的语句，保留工具分发和全部测试断言。文件仍会写入，但 `test_observation_is_backfed_before_second_request` 会在第二次请求的消息顺序处失败，因为历史只有 user、assistant，缺少紧随其后的 user `tool_result`。

### 3. 最小修复

每轮先把完整 assistant `tool_use` 内容加入历史，再按出现顺序执行工具。将结果序列化为 `tool_result.content`，复制当前调用的 `id` 到 `tool_use_id`；同一 assistant 响应的多个结果组成一个 user 消息，随后才能发出下一次模型请求。

修复没有修改 FileTool、工具权限、Fake 最终回答或测试断言。

## 四、协议迁移说明

旧 Chat Completions 接口中的 `function.arguments` 是一层 JSON 字符串，所以本地程序必须再执行一次 `json.loads()`。Anthropic Messages 响应整体经过 HTTP JSON 解码后，`tool_use.input` 已经是对象，本地工具层直接做字段和类型校验；如果继续把它当字符串解码，反而会产生类型错误。

Anthropic Messages 也没有独立的 `role="tool"`。模型工具申请位于 assistant 的 `tool_use` 内容块，执行结果位于下一条 user 消息的 `tool_result` 内容块。这个相邻顺序和 ID 配对是本轮回灌测试的核心。

## 五、结论边界

Fake 能证明控制流、历史、调用顺序和本地工具结果；HTTP Mock 能证明 DeepSeek 与 GLM 共用同一请求构造和响应解析。它们不证明真实密钥、账号套餐、模型名或远端服务当前可用。真实 API 是否可用，需要用户配置对应环境变量后单独运行入口命令验证。

## 六、Lab01 至 Lab03 完整性回归

对比 `fef7e5e` 与 `e647540` 后，恢复了曾被删除的 `init_project.py`、`app/cli/__init__.py` 和 `app/core/__init__.py`，并在 README 中补回脚手架运行说明。Lab01 测试验证 `hello`、空名字、`version`、动态 `help`，以及脚手架的幂等和不覆盖行为；Lab02 原有 30 项测试保持通过。

Lab03 将 Fake Client 从测试文件内部提取为正式模块，并通过唯一入口提供离线演示：

```bash
python main.py agent '完成四工具任务' --fake --root demo_lab03 --trace
```

该命令在不使用 API Key 的情况下完成五次模型请求，真实执行目录列举、文件读取、文件写入和固定 echo，并可继续执行同会话追问。最终回归结果为：Lab01 4 项、Lab02 30 项、Lab03 43 项，共 77 项通过。
