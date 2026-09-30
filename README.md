# AI Coding Agent CLI

一个从命令行、文件工具扩展到 LLM Tool Calling 与最小 ReAct Agent 的 Python 项目。

项目只有一个程序入口：`main.py`。模型层统一使用 Anthropic Messages HTTP/JSON 契约，不依赖模型 SDK 或 Agent 框架；通过 `--provider` 在 DeepSeek 与 GLM 之间切换。

## 安装

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` 只列项目直接依赖，pip 会自动安装这些包需要的间接依赖。

## 基础命令

```bash
python main.py hello
python main.py hello --name NAME
python main.py version
python main.py help
```

## 目录脚手架

Lab01 的 `init_project.py` 用于补齐课程目录和 Python 包标记。脚本可以重复运行，且不会覆盖已有的 `__init__.py`：

```bash
python init_project.py
```

## 离线 Fake 演示

不配置 API Key 也可以通过唯一入口运行确定性的工具调用轨迹。目录枚举、文本与二进制文件操作以及固定命令仍由本地程序真实执行：

```bash
python main.py agent '列目录、读取 notes.txt、写报告并执行固定 echo' \
  --fake --root test_path --trace
```

## DeepSeek

DeepSeek 默认模型为 `deepseek-flash`，也可用 `DEEPSEEK_MODEL` 或 `--model` 覆盖：

```bash
export DEEPSEEK_API_KEY='你的密钥'
python main.py chat '请用一句话解释 Observation' --provider deepseek
python main.py agent '列目录，读取 notes.txt，再根据真实内容回答' \
  --provider deepseek --root test_path --trace
```

## GLM

GLM 的模型名需要显式提供，以免把 Coding Plan 与按量 API 的可用模型混为一谈：

```bash
export GLM_API_KEY='你的密钥'
export GLM_MODEL='你的账号可用的模型名'
python main.py chat '你好' --provider glm
python main.py agent '读取 notes.txt 并总结' \
  --provider glm --root test_path \
  --follow-up '刚才读取的文件叫什么？'
```

默认 GLM Messages 地址是 `https://open.bigmodel.cn/api/anthropic/v1/messages`。如果账号属于其他区域、套餐或代理服务，可用 `--base-url` 传入完整的 `/v1/messages` 地址；消息格式、Agent 和工具层无需改动。

## 工具边界

Agent 当前注册了八个本地工具：`read_file`、`write_file`、`list_dir`、`execute_command`、`append_file`、`read_lines`、`read_bytes`、`write_bytes`。Schema、参数校验与执行函数共用一份注册表，避免新增工具时出现配置不一致。

- 文件工具只能访问 `--root` 下的相对路径；
- `write_file` 不覆盖已有文件；`write_bytes` 保持 `FileTool.write_bytes()` 的覆盖语义；
- 二进制内容通过 Base64 字符串在 JSON 消息中传递；
- Shell 只允许完整匹配 `echo lab03-shell-ok` 和当前平台的查看目录命令；
- 模型返回的工具名、字段和类型都由本地程序再次校验；
- 一次任务达到 `--max-iterations` 后直接退出，不额外请求模型总结。

## 测试

```bash
.venv/bin/python -m pytest -q
```

测试使用 Fake Client 与 `httpx.MockTransport`，不会调用真实 API，也不会消耗额度。
