# ClaudeCliTool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `ClaudeCliTool` to HelloAgents that wraps the local `claude` CLI, allowing agents to invoke Claude for code analysis and understanding tasks with configurable working directory and session reuse.

**Architecture:** Single `Tool` subclass using `subprocess.run` with argument-list invocation (no shell), `cwd` for directory switching, and stdout/stderr capture. Follows the exact pattern of `TerminalTool` but with a fixed target command and no command whitelist.

**Tech Stack:** Python 3.10+, standard library only (`subprocess`, `shutil`, `pathlib`). No new dependencies.

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `tools/builtin/claude_cli_tool.py` | Create | `ClaudeCliTool` class implementation |
| `tools/builtin/__init__.py` | Modify | Add `ClaudeCliTool` to exports |
| `tools/__init__.py` | Modify | Add `ClaudeCliTool` to top-level exports |

---

### Task 1: Implement `ClaudeCliTool`

**Files:**
- Create: `tools/builtin/claude_cli_tool.py`
- Reference: `tools/builtin/terminal_tool.py` (for subprocess pattern)
- Reference: `tools/base.py` (for `Tool`, `ToolParameter` base classes)

- [x] **Step 1: Create the tool file with imports and class skeleton**

```python
"""ClaudeCliTool - 通过本地 Claude CLI 执行代码分析与理解任务"""

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from ..base import Tool, ToolParameter


class ClaudeCliTool(Tool):
    """Claude CLI 工具

    通过本地安装的 `claude` 命令调用 Claude，用于代码分析、理解、审查等任务。
    支持指定工作目录和 session 复用。

    用法示例:
        tool = ClaudeCliTool()
        result = tool.run({
            "prompt": "分析这个项目的架构",
            "working_dir": "/home/hl/my-project",
            "session_id": "analysis-01"
        })
    """

    def __init__(
        self,
        default_working_dir: str = ".",
        default_timeout: int = 120,
        default_dangerously_skip_permissions: bool = True,
        max_output_size: int = 50 * 1024,  # 50KB
    ):
        super().__init__(
            name="claude_cli",
            description="调用本地 Claude CLI 执行代码分析、理解和推理任务"
        )
        self.default_working_dir = default_working_dir
        self.default_timeout = default_timeout
        self.default_dangerously_skip_permissions = default_dangerously_skip_permissions
        self.max_output_size = max_output_size

    def get_parameters(self) -> List[ToolParameter]:
        """获取工具参数定义"""
        return [
            ToolParameter(
                name="prompt",
                type="string",
                description="发送给 Claude 的提示词。示例: '分析这个函数的复杂度'",
                required=True,
            ),
            ToolParameter(
                name="working_dir",
                type="string",
                description="执行命令的工作目录（默认当前目录）",
                required=False,
                default=self.default_working_dir,
            ),
            ToolParameter(
                name="session_id",
                type="string",
                description="Claude session ID，用于复用上下文",
                required=False,
            ),
            ToolParameter(
                name="dangerously_skip_permissions",
                type="boolean",
                description="是否自动跳过权限提示",
                required=False,
                default=self.default_dangerously_skip_permissions,
            ),
            ToolParameter(
                name="timeout",
                type="integer",
                description="命令执行超时秒数",
                required=False,
                default=self.default_timeout,
            ),
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        """执行 Claude CLI 命令"""
        if not self.validate_parameters(parameters):
            return "❌ 参数验证失败：缺少必需的 prompt 参数"

        prompt = parameters.get("prompt", "").strip()
        if not prompt:
            return "❌ prompt 不能为空"

        # 检查 claude 命令是否存在
        claude_path = shutil.which("claude")
        if not claude_path:
            return "❌ 未找到 claude 命令，请确保 Claude CLI 已安装并加入 PATH"

        # 解析工作目录
        working_dir = parameters.get("working_dir", self.default_working_dir)
        working_path = Path(working_dir).resolve()
        if not working_path.exists():
            return f"❌ 工作目录不存在: {working_path}"
        if not working_path.is_dir():
            return f"❌ 工作目录不是有效目录: {working_path}"

        # 构建命令参数列表（避免 shell 注入）
        cmd = [claude_path, "-p", prompt]

        session_id = parameters.get("session_id")
        if session_id:
            cmd.extend(["--session-id", str(session_id)])

        dangerously_skip = parameters.get(
            "dangerously_skip_permissions",
            self.default_dangerously_skip_permissions,
        )
        if dangerously_skip:
            cmd.append("--dangerously-skip-permissions")

        timeout = parameters.get("timeout", self.default_timeout)

        # 执行命令
        try:
            result = subprocess.run(
                cmd,
                cwd=str(working_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"❌ 命令执行超时（超过 {timeout} 秒）"
        except OSError as e:
            return f"❌ 命令执行失败: {e}"
        except Exception as e:
            return f"❌ 执行 Claude CLI 时发生异常: {e}"

        # 合并输出
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"

        # 截断超长输出
        if len(output) > self.max_output_size:
            output = output[: self.max_output_size]
            output += f"\n\n⚠️ 输出被截断（超过 {self.max_output_size} 字节）"

        # 处理非零返回码
        if result.returncode != 0:
            output = f"⚠️ 命令返回码: {result.returncode}\n\n{output}"

        return output if output.strip() else "✅ 命令执行成功（无输出）"
```

- [x] **Step 2: Verify the file syntax**

Run: `python3 -m py_compile tools/builtin/claude_cli_tool.py`
Result: `OK` (no output = success)

- [x] **Step 3: Commit**

```bash
git add tools/builtin/claude_cli_tool.py
git commit -m "feat: add ClaudeCliTool for local Claude CLI invocation

- Wraps local claude command with subprocess.run
- Supports working_dir, session_id, timeout parameters
- Safe argument-list invocation (no shell parsing)
- Output truncation at 50KB to protect token budget

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Register `ClaudeCliTool` in builtin exports

**Files:**
- Modify: `tools/builtin/__init__.py`

- [x] **Step 1: Add import and update `__all__`**

Added import and updated `__all__` in `tools/builtin/__init__.py`.

- [x] **Step 2: Verify import works**

Run: `python3 -c "from tools.builtin import ClaudeCliTool; print('OK')"`
Result: `OK` (import verified)

- [x] **Step 3: Commit**

```bash
git add tools/builtin/__init__.py
git commit -m "chore: register ClaudeCliTool in builtin exports

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Register `ClaudeCliTool` in top-level tools exports

**Files:**
- Modify: `tools/__init__.py`

- [x] **Step 1: Add import and update `__all__`**

Added import and updated `__all__` in `tools/__init__.py`.

- [x] **Step 2: Verify top-level import works**

Run: `python3 -c "from tools import ClaudeCliTool; print('OK')"`
Result: `OK` (import verified; `hello_agents.tools` requires package install)

- [x] **Step 3: Commit**

```bash
git add tools/__init__.py
git commit -m "chore: register ClaudeCliTool in top-level tools exports

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Spec Coverage Check

| Spec Requirement | Implementing Task | Notes |
|---|---|---|
| File at `tools/builtin/claude_cli_tool.py` | Task 1 | ✅ |
| Inherit from `Tool` | Task 1 | ✅ `class ClaudeCliTool(Tool)` |
| `run(parameters)` method | Task 1 | ✅ |
| `get_parameters()` method | Task 1 | ✅ returns 5 `ToolParameter`s |
| `prompt` parameter (required) | Task 1 | ✅ |
| `working_dir` parameter | Task 1 | ✅ defaults to `"."` |
| `session_id` parameter | Task 1 | ✅ optional, maps to `--session-id` |
| `dangerously_skip_permissions` parameter | Task 1 | ✅ defaults to `True` |
| `timeout` parameter | Task 1 | ✅ defaults to `120` |
| Check `claude` in PATH via `shutil.which` | Task 1 | ✅ |
| Validate `working_dir` exists and is a directory | Task 1 | ✅ |
| Build command as argument list (no shell) | Task 1 | ✅ `cmd = [claude_path, "-p", prompt]` |
| Use `subprocess.run(cwd=...)` | Task 1 | ✅ |
| Capture stdout + stderr | Task 1 | ✅ |
| Truncate output at 50KB | Task 1 | ✅ |
| Handle non-zero exit code | Task 1 | ✅ prefixes output with return code |
| Handle `TimeoutExpired` | Task 1 | ✅ |
| Handle `OSError` / generic exceptions | Task 1 | ✅ |
| Register in `tools/builtin/__init__.py` | Task 2 | ✅ |
| Register in `tools/__init__.py` | Task 3 | ✅ |

---

## Placeholder Scan

- [x] No "TBD", "TODO", "implement later", "fill in details"
- [x] No vague "add appropriate error handling" without specifics
- [x] No "write tests for the above" without test code
- [x] No "similar to Task N" cross-references
- [x] Every step that changes code shows the code
- [x] All commands have expected output specified
- [x] Type/method names consistent across tasks (`ClaudeCliTool`, `claude_cli`, `claude_cli_tool.py`)

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-14-claude-cli-tool.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
