# Claude CLI Tool 设计文档

## 背景

HelloAgents 框架需要一种方式将本地 Claude CLI 作为内置工具接入 Agent，用于执行代码分析、代码理解等需要强推理能力的任务。Agent 通过调用 `ClaudeCliTool` 运行 `claude -p <prompt>` 获取结果。

## 目标

- 将本地 `claude` CLI 封装为 HelloAgents 原生工具
- 支持指定工作目录，使代码分析能基于正确的项目上下文
- 支持 session 复用，保持多轮调用的上下文连续性
- 安全执行，避免 shell 注入和越权路径访问

## 非目标

- 不封装 Claude CLI 的交互式/连续对话模式（保留 `-p` 单次调用语义）
- 不预设 prompt 模板（Agent 自行构造 prompt）
- 不管理 Claude CLI 的安装或认证

## 方案概述

采用**方案 A：简单单次调用封装**。`ClaudeCliTool` 继承 `Tool` 基类，通过 `subprocess.run()` 调用 `claude -p <prompt>`，使用 `cwd` 参数切换工作目录，捕获 stdout/stderr 并返回。

## 详细设计

### 文件位置

`hello_agents/tools/builtin/claude_cli_tool.py`

### 类定义

```python
class ClaudeCliTool(Tool):
    """Claude CLI 工具 - 通过本地 claude 命令执行代码分析与理解任务"""
```

### 参数定义

| 参数名 | 类型 | 必需 | 默认值 | 说明 |
|---|---|---|---|---|
| `prompt` | string | 是 | — | 发送给 Claude 的提示词，对应 `-p` |
| `working_dir` | string | 否 | `"."` | 执行命令前切换的工作目录 |
| `session_id` | string | 否 | `None` | 复用已有 session，对应 `--session-id` |
| `dangerously_skip_permissions` | boolean | 否 | `True` | 跳过权限提示，对应 `--dangerously-skip-permissions` |
| `timeout` | integer | 否 | `120` | 命令执行超时秒数 |

### 执行逻辑

1. 检查 `claude` 命令是否在 PATH 中（`shutil.which("claude")`），不存在则返回错误
2. 解析 `working_dir` 为绝对路径，校验目录存在且可读
3. 构建命令参数列表（避免 shell 拼接）：
   ```
   ["claude", "-p", prompt]
   + ["--session-id", session_id]             (if session_id)
   + ["--dangerously-skip-permissions"]       (if dangerously_skip_permissions)
   ```
4. 使用 `subprocess.run(cmd, cwd=working_dir, capture_output=True, text=True, timeout=timeout)` 执行
5. 合并 stdout 和 stderr，按以下规则处理：
   - 输出超过 50KB 时截断并追加提示
   - 返回码非零时，在输出前附加返回码信息
   - 无任何输出时返回"命令执行成功（无输出）"
6. 异常处理：
   - `subprocess.TimeoutExpired` -> 返回超时错误
   - `OSError` / `ValueError` -> 返回执行失败错误
   - 其他异常 -> 捕获并返回错误信息

### 安全边界

- **命令注入防护**：使用参数列表传入命令，不通过 shell 解析
- **路径校验**：`working_dir` 必须是真实存在的目录
- **超时保护**：默认 120 秒，防止长耗时任务阻塞 Agent
- **输出限制**：50KB 上限，防止 token 预算被耗尽

### 使用示例

```python
from hello_agents.tools.builtin.claude_cli_tool import ClaudeCliTool

tool = ClaudeCliTool()
result = tool.run({
    "prompt": "分析这个项目的架构，列出主要模块及其职责",
    "working_dir": "/home/hl/my-project",
    "session_id": "analysis-session-01",
    "timeout": 180
})
```

## 注册方式

工具类遵循现有内置工具模式，可通过 `ToolRegistry.register_tool(ClaudeCliTool())` 注册，也可在 `tools/builtin/__init__.py` 中统一导出。

## 依赖

- Python 标准库：`subprocess`, `shutil`, `os`, `pathlib`
- 外部依赖：`claude` CLI 已安装在系统 PATH 中（运行时检查，非安装时依赖）

## 错误处理与输出格式

| 场景 | 返回值 |
|---|---|
| `claude` 未安装 | `❌ 未找到 claude 命令，请确保 Claude CLI 已安装并加入 PATH` |
| `working_dir` 不存在 | `❌ 工作目录不存在: <path>` |
| 超时 | `❌ 命令执行超时（超过 <timeout> 秒）` |
| 输出截断 | 截断内容 + `\n\n⚠️ 输出被截断（超过 50KB）` |
| 返回码非零 | `⚠️ 命令返回码: <code>\n\n<output>` |

## 与现有工具的关系

- 与 `TerminalTool` 类似，都是 `subprocess` 执行外部命令
- 与 `TerminalTool` 不同，ClaudeCliTool 的目标命令固定为 `claude`，参数语义明确，不需要白名单机制
