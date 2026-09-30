## Lab 2 0916

### 1 open(mode = *) 与 Path.open(mode = *) 用法：

#### i 基础模式（四选一）

| 模式 | 名称 | 含义 | 文件不存在时 | 文件已存在时 | 是否截断 |
|---|---|---|---|---|---|
| `r` | 只读 | 打开文件用于读取 | 报错 `FileNotFoundError` | 从头读 | 否 |
| `w` | 只写 | 打开文件用于写入 | 创建新文件 | **清空原内容** | 是 |
| `a` | 追加写 | 打开文件用于追加写入 | 创建新文件 | 在末尾追加 | 否 |
| `x` | 独占创建 | 打开文件用于写入，且必须不存在 | 创建新文件 | 报错 `FileExistsError` | 不适用 |

默认模式是 `r`。


#### ii 修饰符（可组合）

| 修饰符 | 含义 | 说明 |
|---|---|---|
| `b` | 二进制模式 | 读写 `bytes`，不能指定 `encoding` |
| `t` | 文本模式 | 读写 `str`，默认模式，可指定 `encoding` |
| `+` | 读写模式 | 同时支持读和写，需与 `r`/`w`/`a`/`x` 组合 |

注意：

- `b` 和 `t` 不能同时出现；
- `t` 是默认的，通常省略；
- `+` 让文件同时可读可写。

#### iii 常见组合模式

| 模式 | 读/写 | 文件不存在时 | 文件已存在时 | 是否截断 | 初始读写位置 | 数据单位 |
|---|---|---|---|---|---|---|
| `r` | 只读 | 报错 | 从头读 | 否 | 开头 | `str` |
| `rb` | 只读二进制 | 报错 | 从头读 | 否 | 开头 | `bytes` |
| `r+` | 读写 | 报错 | 不截断，可读可写 | 否 | 开头 | `str` |
| `rb+` / `r+b` | 读写二进制 | 报错 | 不截断，可读可写 | 否 | 开头 | `bytes` |
| `w` | 只写 | 创建 | **清空** | 是 | 开头 | `str` |
| `wb` | 只写二进制 | 创建 | **清空** | 是 | 开头 | `bytes` |
| `w+` | 读写 | 创建 | **清空** | 是 | 开头 | `str` |
| `wb+` / `w+b` | 读写二进制 | 创建 | **清空** | 是 | 开头 | `bytes` |
| `a` | 只写追加 | 创建 | 末尾追加 | 否 | 末尾 | `str` |
| `ab` | 只写追加二进制 | 创建 | 末尾追加 | 否 | 末尾 | `bytes` |
| `a+` | 读写追加 | 创建 | 末尾追加 | 否 | 末尾（读前常需 `seek(0)`） | `str` |
| `ab+` / `a+b` | 读写追加二进制 | 创建 | 末尾追加 | 否 | 末尾 | `bytes` |
| `x` | 只写独占创建 | 创建 | 报错 `FileExistsError` | 不适用 | 开头 | `str` |
| `xb` | 只写二进制独占创建 | 创建 | 报错 | 不适用 | 开头 | `bytes` |
| `x+` | 读写独占创建 | 创建 | 报错 | 不适用 | 开头 | `str` |
| `xb+` / `x+b` | 读写二进制独占创建 | 创建 | 报错 | 不适用 | 开头 | `bytes` |

#### iv 几个关键区别

##### `r+` vs `w+`

| 模式 | 文件不存在 | 文件已存在 | 是否清空 |
|---|---|---|---|
| `r+` | 报错 | 保留内容，可读可写 | 否 |
| `w+` | 创建 | **清空** | 是 |

##### `a` vs `a+`

- `a`：只能写，写入总在末尾；
- `a+`：可读可写，写入也在末尾，但初始读取位置在末尾，想从头读通常要 `seek(0)`。

##### `x` 的用途

防止误覆盖：

```python
with open("config.txt", "x", encoding="utf-8") as f:
    f.write("new")
```

如果 `config.txt` 已存在，直接报 `FileExistsError`，不会清空原文件。

#### v 文本模式 vs 二进制模式

| 模式 | 读写类型 | 能否指定 `encoding` | 换行转换 |
|---|---|---|---|
| 文本模式（默认，`t`） | `str` | 可以 | 默认会转换换行符 |
| 二进制模式（`b`） | `bytes` | 不能 | 不转换 |

示例：

```python
# 文本模式
with open("a.txt", "r", encoding="utf-8") as f:
    text = f.read()          # str

# 二进制模式
with open("a.bin", "rb") as f:
    data = f.read()          # bytes
```

---

## Lab 3 0923

### 1 Anthropic 和 OpenAI 的 API 接口契约

Anthropic Messages API 和 OpenAI Chat Completions API 是当前大模型应用开发中最主流的两种接口契约。它们虽然都用于实现多轮对话，但在设计哲学、数据结构和具体实现上存在显著差异。

#### i 📌 核心架构对比

| 特性 | OpenAI Chat Completions API | Anthropic Messages API |
| :--- | :--- | :--- |
| **端点** | `POST /v1/chat/completions` | `POST /v1/messages` |
| **设计目标** | 无状态文本生成，通用性强 | Claude 原生能力优先，支持扩展思考等 |
| **状态管理** | 完全手动，每次请求需携带完整历史 | 手动，同样需要每次发送完整对话历史 |
| **系统提示** | 作为 `role: "system"` 的消息放入 `messages` 数组 | 使用顶层 `system` 参数，独立于 `messages` |
| **工具调用** | 响应中包含 `tool_calls`，后续用 `role: "tool"` 消息回复 | 使用 `tool_use` 和 `tool_result` 内容块 |
| **流式传输** | SSE，所有事件均为 `data:` 前缀的 JSON | SSE，使用命名事件类型（如 `message_start`） |

#### ii 📨 请求/响应格式详解

##### - 消息模型 (Message Model)
这是两者最根本的区别。

**OpenAI Chat Completions:**
- `messages` 是一个**扁平数组**，每个元素是一个消息对象。
- 消息角色 (`role`) 可以是 `system`, `user`, `assistant`, `tool`。
- `content` 通常是字符串，也可以是内容块数组（用于多模态）。
```json
// OpenAI 请求示例
{
  "model": "gpt-4o",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"},
    {"role": "assistant", "content": [{"type": "text", "text": "Hi!"}]},
    {"role": "user", "content": [{"type": "text", "text": "Nice to meet you!"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "Nice to meet you, too!"}]},
  ]
}
```

**Anthropic Messages:**
- `messages` 数组中只包含 `user` 和 `assistant` 角色，且**必须交替出现**。
- 系统提示通过**顶层**的 `system` 参数传递。
- `content` 总是**内容块数组**，每个块有明确的 `type`（如 `text`, `image`, `tool_use`, `tool_result`）。
```json
// Anthropic 请求示例
{
  "model": "claude-opus-5-5",
  "max_tokens": 1024,
  "system": "You are a helpful assistant.",
  "messages": [
    {"role": "user", "content": [{"type": "text", "text": "Hello!"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "Hi!"}]},
    {"role": "user", "content": [{"type": "text", "text": "Nice to meet you!"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "Nice to meet you, too!"}]},
  ]
}
```

##### - 工具调用 (Tool Calling) 格式
工具调用的数据流差异很大。

**OpenAI:**
1.  请求中定义工具：`tools: [{type: "function", function: {name, description, parameters}}]`。
2.  响应中返回工具调用：`choices[0].message.tool_calls`，其中包含 `id`, `function.name`, `function.arguments`（JSON 字符串）。
3.  提交工具结果：用 `role: "tool"` 的消息，带上 `tool_call_id` 和结果内容。

**Anthropic:**
1.  请求中定义工具：`tools: [{name, description, input_schema}]`。
2.  响应中返回工具调用：内容块数组中出现 `type: "tool_use"` 的块，包含 `id`, `name`, `input`（已解析的 JSON 对象）。
3.  提交工具结果：用 `role: "user"` 的消息，内容块为 `type: "tool_result"`，带上 `tool_use_id` 和结果。

##### - 流式传输 (Streaming)
两者都使用 Server-Sent Events (SSE)，但事件结构不同。

**OpenAI:**
- 每个数据块都是 `data: {...}` 格式的 JSON。
- 通过 `choices[0].delta` 字段增量传输内容。
- 流以 `data: [DONE]` 结束。

**Anthropic:**
- 使用命名事件，如 `event: message_start`, `event: content_block_delta` 等。
- 事件类型更丰富，可以精确追踪消息、内容块的开始、增量、结束。
- 事件类型包括 `message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`, `ping`, `error` 等。

#### iii 🔄 系统提示 (System Prompt) 处理
这是两者一个关键的行为差异。
- **OpenAI**: 系统提示是 `messages` 数组中的一个常规消息，`role` 为 `system`。开发者可以将其放置在数组的任意位置（尽管通常放在开头）。
- **Anthropic**: 系统提示通过顶层的 `system` 参数传递，**不在** `messages` 数组中。Anthropic 只支持**一条**初始系统消息。

Anthropic 官方提供的 **OpenAI SDK 兼容层** 为了弥合这一差异，会将 OpenAI 请求中的所有 `system` 和 `developer` 消息提取出来，用换行符拼接成**单个** `system` 字符串，然后放置在消息列表的开头。

#### iv ⚠️ 错误处理与兼容性限制
当你使用 Anthropic 的 OpenAI 兼容层时，需要注意以下限制：
- **`strict` 参数被忽略**：OpenAI 的 `strict` 工具调用参数会被忽略，这意味着工具调用的 JSON **不保证遵循**你提供的 schema。
- **不支持音频输入**：音频内容会被忽略。
- **不支持提示缓存**：Anthropic 原生的提示缓存功能在兼容层中不可用。
- **不支持的字段被静默忽略**：大多数不支持的字段不会报错，而是被直接忽略。

#### 💎 总结与选择
- **OpenAI Chat Completions API** 是行业的**事实标准**，生态最广，兼容性最好，适合需要跨模型提供商、快速切换的通用场景。
- **Anthropic Messages API** 是**Claude 的原生接口**，能完整发挥 Claude 的高级能力（如扩展思考、提示缓存、计算机使用等），适合深度集成 Claude 的特定应用。
- 两者可以通过**兼容层**互相转换。Anthropic 提供了官方的 OpenAI SDK 兼容层，使得你可以用 OpenAI SDK 调用 Claude 模型，但需注意上述功能限制。许多第三方网关（如 Portkey）也支持在不同 API 格式间进行转换。


### 2 深浅拷贝及其应用

### 3 json 的传输的接受