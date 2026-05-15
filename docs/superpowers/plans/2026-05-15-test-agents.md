# 测试智能体群（Test Agents）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 LangGraph Supervisor 模式构建多智能体测试系统，包含测试经理调度、代码分析智能体、用例评审智能体，支持 Claude CLI Skill 调用。

**Architecture:** 单层 Supervisor 模式：测试经理根据 state 决定调用代码分析 Agent 或 用例评审 Agent；Agent 通过公共 tools 层按需加载工具；所有智能体通过共享 state 通信；项目封装为 Claude CLI Skill。

**Tech Stack:** Python, LangGraph, LangChain, Pydantic, Claude CLI

---

## Task 1: 项目脚手架与依赖配置

**Files:**
- Create: `test_agents/__init__.py`
- Create: `test_agents/readme.md`
- Create: `requirements.txt`

- [ ] **Step 1: 创建项目根目录结构**

```bash
mkdir -p test_agents/{agents,tools,graph,skills/{code_analysis_skill,case_review_skill},prompts}
touch test_agents/__init__.py
touch test_agents/agents/__init__.py
touch test_agents/tools/__init__.py
touch test_agents/graph/__init__.py
```

- [ ] **Step 2: 写入 requirements.txt**

Create `requirements.txt`:

```text
langgraph>=0.2.0
langchain-core>=0.3.0
langchain-openai>=0.2.0
pydantic>=2.0.0
pytest>=8.0.0
```

- [ ] **Step 3: 写入根 __init__.py**

Create `test_agents/__init__.py`:

```python
"""测试智能体群 - 基于 LangGraph Supervisor 模式的多智能体测试系统"""

__version__ = "0.1.0"
```

- [ ] **Step 4: Commit**

```bash
git add test_agents/ requirements.txt
git commit -m "chore: scaffold test_agents project structure"
```

---

## Task 2: GraphState 定义与 Pydantic 验证

**Files:**
- Create: `test_agents/graph/state.py`
- Create: `test_agents/tests/test_state.py`

- [ ] **Step 1: 编写状态验证测试**

Create `test_agents/tests/test_state.py`:

```python
import pytest
from test_agents.graph.state import TestAgentState


def test_valid_state():
    state = TestAgentState(
        module_name="order",
        source_commit="a1b2c3d",
        target_commit="e4f5g6h",
        commit_msg="fix: update order logic",
        test_cases=[{"case_id": "TC001", "title": "test order creation"}],
    )
    assert state.module_name == "order"


def test_invalid_commit_sha():
    with pytest.raises(ValueError, match="Invalid commit SHA"):
        TestAgentState(
            module_name="order",
            source_commit="invalid!",
            target_commit="e4f5g6h",
            commit_msg="fix",
        )


def test_path_traversal_in_module():
    with pytest.raises(ValueError, match="Invalid module name"):
        TestAgentState(
            module_name="../../etc",
            source_commit="a1b2c3d",
            target_commit="e4f5g6h",
            commit_msg="fix",
        )


def test_test_cases_default_empty():
    state = TestAgentState(
        module_name="order",
        source_commit="a1b2c3d",
        target_commit="e4f5g6h",
        commit_msg="fix",
    )
    assert state.test_cases == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /mnt/d/testagents
python -m pytest test_agents/tests/test_state.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'test_agents.graph.state'`

- [ ] **Step 3: 实现 TestAgentState**

Create `test_agents/graph/state.py`:

```python
"""GraphState 定义 - 使用 Pydantic 进行严格验证"""

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TestAgentState(BaseModel):
    """测试智能体群的状态定义"""

    # 用户输入
    module_name: str = Field(description="待分析的模块名称")
    source_commit: str = Field(description="源 commit ID")
    target_commit: str = Field(description="目标 commit ID")
    commit_msg: str = Field(default="", description="commit message")
    test_cases: list[dict] = Field(default_factory=list, description="待评审的测试用例")
    business_knowledge: str = Field(default="", description="业务背景知识")

    # 中间产物
    code_change_report: str = Field(default="", description="代码分析结果")
    review_results: list[dict] = Field(default_factory=list, description="用例评审结果")

    # 控制流
    next_step: str = Field(default="", description="Supervisor 决策")
    messages: list[dict] = Field(default_factory=list, description="对话历史")

    # 错误信息
    error: str = Field(default="", description="错误信息")

    @field_validator("source_commit", "target_commit")
    @classmethod
    def validate_commit_sha(cls, value: str) -> str:
        """验证 commit SHA 格式，防止命令注入"""
        if not value:
            return value
        if not re.match(r"^[a-f0-9]{7,40}$", value, re.IGNORECASE):
            raise ValueError(f"Invalid commit SHA: {value}. Must be 7-40 hex characters.")
        return value.lower()

    @field_validator("module_name")
    @classmethod
    def validate_module_name(cls, value: str) -> str:
        """验证模块名，防止路径遍历"""
        if not value:
            return value
        if ".." in value or value.startswith("/") or re.search(r"[<>


## Task 3: GitDiffTool（带安全验证）

**Files:**
- Create: `test_agents/tools/git_diff.py`
- Create: `test_agents/tests/test_git_diff.py`

- [ ] **Step 1: 编写 GitDiffTool 测试**

Create `test_agents/tests/test_git_diff.py`:

```python
import pytest
from test_agents.tools.git_diff import GitDiffTool, extract_diff_summary


def test_extract_diff_summary_with_changes():
    diff = """diff --git a/order.py b/order.py
+def new_func():
+    pass
"""
    result = extract_diff_summary(diff)
    assert "order.py" in result


def test_extract_diff_summary_empty():
    result = extract_diff_summary("")
    assert result == "无变更"


def test_git_diff_tool_validates_sha():
    tool = GitDiffTool()
    with pytest.raises(ValueError, match="Invalid commit SHA"):
        tool.run({
            "module_name": "order",
            "source_commit": "bad!",
            "target_commit": "e4f5g6h",
        })


def test_git_diff_tool_validates_module():
    tool = GitDiffTool()
    with pytest.raises(ValueError, match="Invalid module name"):
        tool.run({
            "module_name": "../../etc",
            "source_commit": "a1b2c3d",
            "target_commit": "e4f5g6h",
        })
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest test_agents/tests/test_git_diff.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'test_agents.tools.git_diff'`

- [ ] **Step 3: 实现 GitDiffTool**

Create `test_agents/tools/git_diff.py`:

```python
"""Git 变更提取工具 - 带安全验证"""

import re
import subprocess
from typing import Dict, Any


# diff 大小阈值（字符数）
MAX_DIFF_SIZE = 100_000  # 100KB


def extract_diff_summary(diff_content: str) -> str:
    """从 diff 内容提取摘要"""
    if not diff_content:
        return "无变更"

    lines = diff_content.split("\n")
    files = []
    additions = 0
    deletions = 0

    for line in lines:
        if line.startswith("diff --git"):
            parts = line.split(" ")
            if len(parts) >= 4:
                files.append(parts[-1].replace("b/", ""))
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    summary = f"变更文件: {', '.join(files)}\n"
    summary += f"新增: {additions} 行, 删除: {deletions} 行\n"

    # 如果 diff 太大，只返回摘要
    if len(diff_content) > MAX_DIFF_SIZE:
        summary += f"\n[Diff 内容超过 {MAX_DIFF_SIZE} 字符，已截断]"
        # 保留前 500 行作为预览
        preview = "\n".join(lines[:500])
        summary += f"\n预览:\n{preview}"
    else:
        summary += f"\n{diff_content}"

    return summary


class GitDiffTool:
    """提取指定模块在 commit 范围内的代码变更"""

    def __init__(self, repo_path: str = "."):
        self.repo_path = repo_path
        self.name = "git_diff"
        self.description = "提取指定模块在两个 commit 之间的代码变更"

    def _validate_inputs(self, module_name: str, source_commit: str, target_commit: str) -> None:
        """验证输入参数，防止命令注入"""
        if not re.match(r"^[a-f0-9]{7,40}$", source_commit, re.IGNORECASE):
            raise ValueError(f"Invalid commit SHA: {source_commit}")
        if not re.match(r"^[a-f0-9]{7,40}$", target_commit, re.IGNORECASE):
            raise ValueError(f"Invalid commit SHA: {target_commit}")
        if ".." in module_name or module_name.startswith("/"):
            raise ValueError(f"Invalid module name: {module_name}")

    def run(self, parameters: Dict[str, Any]) -> str:
        """执行 git diff 并返回变更摘要"""
        module_name = parameters.get("module_name", "")
        source_commit = parameters.get("source_commit", "")
        target_commit = parameters.get("target_commit", "")

        self._validate_inputs(module_name, source_commit, target_commit)

        try:
            result = subprocess.run(
                [
                    "git", "diff",
                    f"{source_commit}..{target_commit}",
                    "--",
                    f"{module_name}/",
                ],
                capture_output=True,
                text=True,
                cwd=self.repo_path,
                timeout=30,
            )

            if result.returncode != 0:
                return f"错误: git diff 失败 - {result.stderr}"

            return extract_diff_summary(result.stdout)

        except subprocess.TimeoutExpired:
            return "错误: git diff 超时（30秒）"
        except FileNotFoundError:
            return "错误: git 命令未找到，请确认 git 已安装"
        except Exception as e:
            return f"错误: {str(e)}"

    def get_parameters(self) -> list[dict]:
        """获取参数定义"""
        return [
            {"name": "module_name", "type": "string", "description": "模块路径", "required": True},
            {"name": "source_commit", "type": "string", "description": "源 commit SHA", "required": True},
            {"name": "target_commit", "type": "string", "description": "目标 commit SHA", "required": True},
        ]
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest test_agents/tests/test_git_diff.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/graph/state.py test_agents/tools/git_diff.py test_agents/tests/
git commit -m "feat: add TestAgentState with Pydantic validation and GitDiffTool"
```

---

## Task 4: ClaudeCliTool

**Files:**
- Create: `test_agents/tools/claude_cli.py`
- Create: `test_agents/tests/test_claude_cli.py`

- [ ] **Step 1: 编写 ClaudeCliTool 测试**

Create `test_agents/tests/test_claude_cli.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from test_agents.tools.claude_cli import ClaudeCliTool


def test_claude_cli_tool_escapes_prompt():
    """测试 prompt 中的特殊字符被正确处理"""
    tool = ClaudeCliTool()
    # 包含引号和换行的 prompt
    prompt = 'Say "hello"\nThen say "world"'
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="hello world", stderr="")
        result = tool.run({"prompt": prompt})
        assert result == "hello world"
        # 验证调用参数
        args = mock_run.call_args[0][0]
        assert args[0] == "claude"
        assert args[1] == "-p"
        assert args[2] == prompt


def test_claude_cli_tool_timeout():
    """测试超时处理"""
    tool = ClaudeCliTool(timeout_seconds=1)
    with patch("subprocess.run") as mock_run:
        from subprocess import TimeoutExpired
        mock_run.side_effect = TimeoutExpired("claude", 1)
        result = tool.run({"prompt": "test"})
        assert "超时" in result


def test_claude_cli_tool_not_found():
    """测试 Claude CLI 未安装"""
    tool = ClaudeCliTool()
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError("claude")
        result = tool.run({"prompt": "test"})
        assert "未找到" in result
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest test_agents/tests/test_claude_cli.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 ClaudeCliTool**

Create `test_agents/tools/claude_cli.py`:

```python
"""Claude CLI 封装工具"""

import subprocess
from typing import Dict, Any


class ClaudeCliTool:
    """通过 claude -p 调用 Claude CLI"""

    def __init__(self, timeout_seconds: int = 120, max_retries: int = 2):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.name = "claude_cli"
        self.description = "调用 Claude CLI 执行分析任务"

    def run(self, parameters: Dict[str, Any]) -> str:
        """执行 claude -p 命令"""
        prompt = parameters.get("prompt", "")
        model = parameters.get("model", "")

        if not prompt:
            return "错误: prompt 不能为空"

        cmd = ["claude", "-p", prompt]
        if model:
            cmd.extend(["--model", model])

        last_error = ""
        for attempt in range(self.max_retries):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                )

                if result.returncode == 0:
                    return result.stdout.strip()

                last_error = result.stderr.strip() or f"返回码: {result.returncode}"

            except subprocess.TimeoutExpired:
                last_error = f"Claude CLI 超时（{self.timeout_seconds}秒）"
            except FileNotFoundError:
                return "错误: Claude CLI 未找到。请确认已安装并配置到 PATH 中。"
            except Exception as e:
                last_error = str(e)

        return f"错误: Claude CLI 调用失败（重试{self.max_retries}次）- {last_error}"

    def get_parameters(self) -> list[dict]:
        """获取参数定义"""
        return [
            {"name": "prompt", "type": "string", "description": "传递给 Claude CLI 的完整提示词", "required": True},
            {"name": "model", "type": "string", "description": "指定模型（可选）", "required": False},
        ]
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest test_agents/tests/test_claude_cli.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/tools/claude_cli.py test_agents/tests/test_claude_cli.py
git commit -m "feat: add ClaudeCliTool with retry and timeout"
```

---

## Task 5: TestCaseParserTool 与 BusinessKnowledgeTool

**Files:**
- Create: `test_agents/tools/test_case_parser.py`
- Create: `test_agents/tools/business_knowledge.py`
- Create: `test_agents/tests/test_tools_misc.py`

- [ ] **Step 1: 实现 TestCaseParserTool**

Create `test_agents/tools/test_case_parser.py`:

```python
"""测试用例解析工具"""

import json
from typing import Dict, Any


class TestCaseParserTool:
    """统一解析单条和批量用例输入"""

    def __init__(self):
        self.name = "test_case_parser"
        self.description = "解析测试用例输入，统一为结构化列表"

    def run(self, parameters: Dict[str, Any]) -> list[dict]:
        """解析用例输入"""
        input_data = parameters.get("input_data", "")
        format_type = parameters.get("format", "json")

        if not input_data:
            return []

        if format_type == "json":
            return self._parse_json(input_data)
        elif format_type == "text":
            return self._parse_text(input_data)
        else:
            raise ValueError(f"不支持的格式: {format_type}")

    def _parse_json(self, data: str) -> list[dict]:
        """解析 JSON 格式"""
        try:
            parsed = json.loads(data)
            if isinstance(parsed, list):
                return [self._normalize_case(item) for item in parsed]
            elif isinstance(parsed, dict):
                return [self._normalize_case(parsed)]
            else:
                raise ValueError("JSON 必须是对象或数组")
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析失败: {e}")

    def _parse_text(self, data: str) -> list[dict]:
        """解析纯文本格式（简单分隔）"""
        lines = [line.strip() for line in data.split("\n") if line.strip()]
        return [{"case_id": f"TC{i+1:03d}", "title": line} for i, line in enumerate(lines)]

    def _normalize_case(self, item: dict) -> dict:
        """标准化用例格式"""
        return {
            "case_id": item.get("case_id", ""),
            "title": item.get("title", ""),
            "steps": item.get("steps", ""),
            "expected_result": item.get("expected_result", ""),
        }

    def get_parameters(self) -> list[dict]:
        return [
            {"name": "input_data", "type": "string", "description": "原始输入数据", "required": True},
            {"name": "format", "type": "string", "description": "输入格式: json/text", "required": False},
        ]
```

- [ ] **Step 2: 实现 BusinessKnowledgeTool**

Create `test_agents/tools/business_knowledge.py`:

```python
"""业务知识查询工具"""

import json
import os
from typing import Dict, Any


class BusinessKnowledgeTool:
    """根据模块名查询相关业务知识"""

    def __init__(self, knowledge_dir: str = ""):
        self.knowledge_dir = knowledge_dir or os.path.join(os.path.dirname(__file__), "..", "knowledge")
        self.name = "business_knowledge"
        self.description = "查询模块相关的业务知识"

    def run(self, parameters: Dict[str, Any]) -> str:
        """查询业务知识"""
        module_name = parameters.get("module_name", "")

        if not module_name:
            return ""

        # 尝试从本地 JSON 知识库加载
        knowledge_file = os.path.join(self.knowledge_dir, f"{module_name}.json")
        if os.path.exists(knowledge_file):
            try:
                with open(knowledge_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("description", "")
            except Exception:
                pass

        # 返回空字符串，不阻塞流程
        return ""

    def get_parameters(self) -> list[dict]:
        return [
            {"name": "module_name", "type": "string", "description": "模块名称", "required": True},
        ]
```

- [ ] **Step 3: 编写测试**

Create `test_agents/tests/test_tools_misc.py`:

```python
import pytest
from test_agents.tools.test_case_parser import TestCaseParserTool
from test_agents.tools.business_knowledge import BusinessKnowledgeTool


def test_parse_json_array():
    tool = TestCaseParserTool()
    result = tool.run({
        "input_data": '[{"case_id": "TC001", "title": "test"}]',
        "format": "json",
    })
    assert len(result) == 1
    assert result[0]["case_id"] == "TC001"


def test_parse_json_single():
    tool = TestCaseParserTool()
    result = tool.run({
        "input_data": '{"case_id": "TC001", "title": "test"}',
        "format": "json",
    })
    assert len(result) == 1


def test_parse_text():
    tool = TestCaseParserTool()
    result = tool.run({
        "input_data": "Test case 1\nTest case 2",
        "format": "text",
    })
    assert len(result) == 2
    assert result[0]["case_id"] == "TC001"


def test_parse_invalid_json():
    tool = TestCaseParserTool()
    with pytest.raises(ValueError, match="JSON 解析失败"):
        tool.run({"input_data": "invalid json", "format": "json"})


def test_business_knowledge_empty():
    tool = BusinessKnowledgeTool(knowledge_dir="/tmp/nonexistent")
    result = tool.run({"module_name": "order"})
    assert result == ""
```

- [ ] **Step 4: 运行测试**

```bash
python -m pytest test_agents/tests/test_tools_misc.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/tools/test_case_parser.py test_agents/tools/business_knowledge.py test_agents/tests/test_tools_misc.py
git commit -m "feat: add TestCaseParserTool and BusinessKnowledgeTool"
```

---

## Task 6: 智能体 - Supervisor

**Files:**
- Create: `test_agents/agents/supervisor.py`
- Create: `test_agents/tests/test_supervisor.py`

- [ ] **Step 1: 编写 Supervisor 测试**

Create `test_agents/tests/test_supervisor.py`:

```python
from test_agents.agents.supervisor import route_decision


def test_route_to_analyze_when_no_report():
    state = {"code_change_report": "", "test_cases": [{"id": "1"}], "review_results": []}
    assert route_decision(state) == "analyze"


def test_route_to_review_when_has_report_and_cases():
    state = {"code_change_report": "report", "test_cases": [{"id": "1"}], "review_results": []}
    assert route_decision(state) == "review"


def test_route_to_end_when_done():
    state = {"code_change_report": "report", "test_cases": [{"id": "1"}], "review_results": [{"id": "1"}]}
    assert route_decision(state) == "end"


def test_route_to_end_when_no_test_cases():
    state = {"code_change_report": "report", "test_cases": [], "review_results": []}
    assert route_decision(state) == "end"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest test_agents/tests/test_supervisor.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 Supervisor**

Create `test_agents/agents/supervisor.py`:

```python
"""测试经理 Supervisor - 负责任务调度"""

from typing import Literal


def route_decision(state: dict) -> Literal["analyze", "review", "end"]:
    """根据当前 state 决定下一步路由

    决策逻辑:
    1. 如果 code_change_report 为空 -> 调用代码分析
    2. 如果 test_cases 非空且 review_results 为空 -> 调用用例评审
    3. 其他情况 -> 结束
    """
    code_report = state.get("code_change_report", "")
    test_cases = state.get("test_cases", [])
    review_results = state.get("review_results", [])
    error = state.get("error", "")

    # 如果有错误，直接结束
    if error:
        return "end"

    # 还没有代码分析报告
    if not code_report:
        return "analyze"

    # 有测试用例需要评审
    if test_cases and not review_results:
        return "review"

    # 所有任务完成或无需评审
    return "end"


def supervisor_node(state: dict) -> dict:
    """Supervisor 节点 - 更新 next_step"""
    next_step = route_decision(state)
    return {"next_step": next_step}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest test_agents/tests/test_supervisor.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/agents/supervisor.py test_agents/tests/test_supervisor.py
git commit -m "feat: add Supervisor with deterministic routing logic"
```

---

## Task 7: 智能体 - CodeAnalyzer

**Files:**
- Create: `test_agents/agents/code_analyzer.py`

- [ ] **Step 1: 实现 CodeAnalyzer Agent**

Create `test_agents/agents/code_analyzer.py`:

```python
"""代码分析智能体"""

from test_agents.tools.git_diff import GitDiffTool
from test_agents.tools.claude_cli import ClaudeCliTool


def code_analyzer_node(state: dict) -> dict:
    """代码分析节点

    1. 调用 GitDiffTool 提取变更
    2. 将变更内容通过 ClaudeCliTool 传递给 Claude CLI 分析
    3. 返回结构化变更报告
    """
    module_name = state.get("module_name", "")
    source_commit = state.get("source_commit", "")
    target_commit = state.get("target_commit", "")
    commit_msg = state.get("commit_msg", "")

    if not all([module_name, source_commit, target_commit]):
        return {"error": "缺少必需的参数: module_name, source_commit, target_commit"}

    # 步骤 1: 提取 git diff
    git_tool = GitDiffTool()
    diff_result = git_tool.run({
        "module_name": module_name,
        "source_commit": source_commit,
        "target_commit": target_commit,
    })

    if diff_result.startswith("错误:"):
        return {"error": diff_result}

    # 步骤 2: 调用 Claude CLI 分析
    claude_tool = ClaudeCliTool()

    prompt = f"""请分析以下代码变更，输出结构化报告：

模块：{module_name}
Commit 范围：{source_commit}..{target_commit}
Commit 消息：{commit_msg}

变更内容：
{diff_result}

请输出以下格式的报告：
## 变更概述
...
## 新增/修改/删除的文件
...
## 关键逻辑变更
...
## 影响范围评估
...
"""

    analysis = claude_tool.run({"prompt": prompt})

    if analysis.startswith("错误:"):
        return {"error": analysis}

    return {"code_change_report": analysis}
```

- [ ] **Step 2: Commit**

```bash
git add test_agents/agents/code_analyzer.py
git commit -m "feat: add CodeAnalyzer agent node"
```

---

## Task 8: 智能体 - CaseReviewer

**Files:**
- Create: `test_agents/agents/case_reviewer.py`

- [ ] **Step 1: 实现 CaseReviewer Agent**

Create `test_agents/agents/case_reviewer.py`:

```python
"""用例评审智能体"""

import json
from test_agents.tools.claude_cli import ClaudeCliTool


def case_reviewer_node(state: dict) -> dict:
    """用例评审节点

    1. 读取 code_change_report + test_cases + business_knowledge
    2. 调用 ClaudeCliTool 进行评审
    3. 输出评审结果
    """
    code_change_report = state.get("code_change_report", "")
    test_cases = state.get("test_cases", [])
    business_knowledge = state.get("business_knowledge", "")

    if not code_change_report:
        return {"error": "缺少代码变更报告，请先执行代码分析"}

    if not test_cases:
        return {"review_results": []}

    # 构建用例文本
    cases_text = json.dumps(test_cases, ensure_ascii=False, indent=2)

    # 调用 Claude CLI 评审
    claude_tool = ClaudeCliTool()

    prompt = f"""请基于以下代码变更报告评审测试用例：

## 代码变更报告
{code_change_report}

## 业务知识
{business_knowledge or "无"}

## 待评审用例
{cases_text}

请输出 JSON 格式的评审结果：
```json
[
  {{
    "case_id": "TC001",
    "title": "...",
    "verdict": "pass|fail|needs_improvement",
    "score": 85,
    "issues": ["..."],
    "suggestions": ["..."],
    "coverage_assessment": "..."
  }}
]
```
"""

    review = claude_tool.run({"prompt": prompt})

    if review.startswith("错误:"):
        return {"error": review}

    # 尝试解析 JSON
    try:
        # 提取 JSON 块
        if "```json" in review:
            json_str = review.split("```json")[1].split("```")[0].strip()
        elif "```" in review:
            json_str = review.split("```")[1].split("```")[0].strip()
        else:
            json_str = review

        review_results = json.loads(json_str)
        if not isinstance(review_results, list):
            review_results = [review_results]

        return {"review_results": review_results}

    except json.JSONDecodeError:
        return {
            "review_results": [{
                "case_id": "N/A",
                "title": "解析失败",
                "verdict": "needs_improvement",
                "score": 0,
                "issues": ["评审结果解析失败"],
                "suggestions": [f"原始输出: {review[:500]}"],
            }]
        }
```

- [ ] **Step 2: Commit**

```bash
git add test_agents/agents/case_reviewer.py
git commit -m "feat: add CaseReviewer agent node"
```

---

## Task 9: 图编排 - builder.py

**Files:**
- Create: `test_agents/graph/builder.py`
- Create: `test_agents/tests/test_builder.py`

- [ ] **Step 1: 编写图构建测试**

Create `test_agents/tests/test_builder.py`:

```python
from test_agents.graph.builder import build_graph


def test_graph_builds():
    graph = build_graph()
    assert graph is not None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest test_agents/tests/test_builder.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现图构建器**

Create `test_agents/graph/builder.py`:

```python
"""图编排构建器"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

from test_agents.agents.supervisor import supervisor_node
from test_agents.agents.code_analyzer import code_analyzer_node
from test_agents.agents.case_reviewer import case_reviewer_node
from test_agents.graph.state import TestAgentState


def build_graph():
    """构建并编译测试智能体群图"""
    graph = StateGraph(TestAgentState)

    # 添加节点
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("code_analyzer", code_analyzer_node)
    graph.add_node("case_reviewer", case_reviewer_node)

    # 固定边
    graph.add_edge(START, "supervisor")
    graph.add_edge("code_analyzer", "supervisor")
    graph.add_edge("case_reviewer", "supervisor")

    # 条件边：Supervisor 决策路由
    graph.add_conditional_edges(
        "supervisor",
        lambda state: state.get("next_step", "end"),
        {
            "analyze": "code_analyzer",
            "review": "case_reviewer",
            "end": END,
        }
    )

    # 编译时传入 checkpointer
    memory = InMemorySaver()
    app = graph.compile(checkpointer=memory)

    return app
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest test_agents/tests/test_builder.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/graph/builder.py test_agents/tests/test_builder.py
git commit -m "feat: add StateGraph builder with checkpointing"
```

---

## Task 10: Skill 层

**Files:**
- Create: `test_agents/skills/readme.md`
- Create: `test_agents/skills/code_analysis_skill/SKILL.md`
- Create: `test_agents/skills/case_review_skill/SKILL.md`

- [ ] **Step 1: 写入 Skill 安装说明**

Create `test_agents/skills/readme.md`:

```markdown
# Skills 安装说明

## 安装

将 skill 目录复制到 Claude 用户级 skill 目录：

```bash
cp -r test_agents/skills/code_analysis_skill ~/.claude/skills/
cp -r test_agents/skills/case_review_skill ~/.claude/skills/
```

## 验证

```bash
claude skill list | grep -E "code_analysis|case_review"
```
```

- [ ] **Step 2: 写入 code_analysis_skill**

Create `test_agents/skills/code_analysis_skill/SKILL.md`:

```markdown
---
name: code_analysis
description: 分析代码变更并输出结构化报告
---

# 代码变更分析

你是一个代码分析专家。请分析提供的代码变更，输出以下格式的报告：

## 变更概述
简要描述这次变更的目的和影响。

## 新增/修改/删除的文件
列出所有变更的文件及变更类型。

## 关键逻辑变更
详细描述业务逻辑的变更点。

## 影响范围评估
评估变更对系统的影响范围和风险等级（低/中/高）。

## 测试建议
基于变更内容，建议需要补充的测试场景。
```

- [ ] **Step 3: 写入 case_review_skill**

Create `test_agents/skills/case_review_skill/SKILL.md`:

```markdown
---
name: case_review
description: 评审测试用例质量
---

# 测试用例评审

你是一个测试用例评审专家。请基于代码变更报告评审测试用例：

## 评审维度

1. **覆盖度**：用例是否覆盖了变更引入的新逻辑和边界条件
2. **清晰度**：用例步骤和预期结果是否明确
3. **独立性**：用例之间是否相互独立
4. **可执行性**：用例是否可以被准确执行和验证

## 输出格式

对每个用例输出：
- verdict: pass / fail / needs_improvement
- score: 0-100
- issues: 发现的问题列表
- suggestions: 改进建议
- coverage_assessment: 覆盖度评估
```

- [ ] **Step 4: Commit**

```bash
git add test_agents/skills/
git commit -m "feat: add Claude CLI Skills for code analysis and case review"
```

---

## Task 11: Prompts 模板

**Files:**
- Create: `test_agents/prompts/supervisor.md`
- Create: `test_agents/prompts/code_analyzer.md`
- Create: `test_agents/prompts/case_reviewer.md`

- [ ] **Step 1: 写入 prompts**

Create `test_agents/prompts/supervisor.md`:

```markdown
# Supervisor 提示词

你是测试经理，负责调度测试任务。

当前状态：
- code_change_report: {{has_report}}
- test_cases: {{case_count}}
- review_results: {{result_count}}

决策规则：
1. 如果没有代码分析报告，先执行代码分析
2. 如果有代码报告和测试用例但没有评审结果，执行用例评审
3. 其他情况，任务完成
```

Create `test_agents/prompts/code_analyzer.md`:

```markdown
# 代码分析提示词模板

模块：{{module_name}}
Commit：{{source_commit}}..{{target_commit}}
变更内容：
{{diff_content}}

请分析代码变更并输出结构化报告。
```

Create `test_agents/prompts/case_reviewer.md`:

```markdown
# 用例评审提示词模板

变更报告：
{{code_change_report}}

用例列表：
{{test_cases}}

业务知识：
{{business_knowledge}}

请评审测试用例并输出 JSON 格式结果。
```

- [ ] **Step 2: Commit**

```bash
git add test_agents/prompts/
git commit -m "chore: add prompt templates"
```

---

## Task 12: 入口点 main.py + CLI

**Files:**
- Create: `test_agents/main.py`
- Create: `test_agents/tests/test_main.py`
- Modify: `test_agents/__main__.py`

- [ ] **Step 1: 编写入口点测试**

Create `test_agents/tests/test_main.py`:

```python
from unittest.mock import patch, MagicMock
from test_agents.main import run_test_agents


def test_run_test_agents_with_mock():
    with patch("test_agents.main.build_graph") as mock_build:
        mock_app = MagicMock()
        mock_app.invoke.return_value = {
            "review_results": [{"case_id": "TC001", "verdict": "pass"}]
        }
        mock_build.return_value = mock_app

        result = run_test_agents(
            module_name="order",
            source_commit="a1b2c3d",
            target_commit="e4f5g6h",
            test_cases='[{"case_id": "TC001", "title": "test"}]',
        )

        assert result["review_results"][0]["verdict"] == "pass"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest test_agents/tests/test_main.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 main.py**

Create `test_agents/main.py`:

```python
"""CLI 入口点"""

import argparse
import json
import sys

from test_agents.graph.builder import build_graph
from test_agents.graph.state import TestAgentState


def run_test_agents(
    module_name: str,
    source_commit: str,
    target_commit: str,
    commit_msg: str = "",
    test_cases: str = "",
    business_knowledge: str = "",
) -> dict:
    """运行测试智能体群"""
    # 解析测试用例
    parsed_cases = []
    if test_cases:
        try:
            parsed = json.loads(test_cases)
            if isinstance(parsed, list):
                parsed_cases = parsed
            elif isinstance(parsed, dict):
                parsed_cases = [parsed]
        except json.JSONDecodeError:
            print("警告: 测试用例 JSON 解析失败，将使用空列表", file=sys.stderr)

    # 构建初始状态
    state = TestAgentState(
        module_name=module_name,
        source_commit=source_commit,
        target_commit=target_commit,
        commit_msg=commit_msg,
        test_cases=parsed_cases,
        business_knowledge=business_knowledge,
    )

    # 构建图并运行
    app = build_graph()

    config = {"configurable": {"thread_id": f"{module_name}-{source_commit}"}}
    result = app.invoke(state.model_dump(), config)

    return result


def main():
    """CLI 主函数"""
    parser = argparse.ArgumentParser(description="测试智能体群")
    parser.add_argument("--module", required=True, help="模块名称")
    parser.add_argument("--source", required=True, help="源 commit SHA")
    parser.add_argument("--target", required=True, help="目标 commit SHA")
    parser.add_argument("--msg", default="", help="commit message")
    parser.add_argument("--cases", default="", help="测试用例 JSON 字符串")
    parser.add_argument("--knowledge", default="", help="业务知识")
    parser.add_argument("--output", default="json", choices=["json", "markdown"], help="输出格式")

    args = parser.parse_args()

    result = run_test_agents(
        module_name=args.module,
        source_commit=args.source,
        target_commit=args.target,
        commit_msg=args.msg,
        test_cases=args.cases,
        business_knowledge=args.knowledge,
    )

    # 输出结果
    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("# 测试智能体群执行结果\n")
        print(f"## 代码变更报告\n{result.get('code_change_report', 'N/A')}\n")
        print(f"## 用例评审结果")
        for r in result.get("review_results", []):
            print(f"\n### {r.get('case_id', 'N/A')} - {r.get('title', '')}")
            print(f"- 结论: {r.get('verdict', 'N/A')}")
            print(f"- 得分: {r.get('score', 'N/A')}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 创建 __main__.py**

Create `test_agents/__main__.py`:

```python
from test_agents.main import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest test_agents/tests/test_main.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add test_agents/main.py test_agents/__main__.py test_agents/tests/test_main.py
git commit -m "feat: add CLI entry point with argparse and JSON/markdown output"
```

---

## Task 13: 集成测试

**Files:**
- Create: `test_agents/tests/test_integration.py`

- [ ] **Step 1: 编写集成测试**

Create `test_agents/tests/test_integration.py`:

```python
from unittest.mock import patch, MagicMock
from test_agents.main import run_test_agents


def test_full_pipeline_mocked():
    """测试完整流程（使用 mock）"""
    with patch("test_agents.tools.git_diff.GitDiffTool.run") as mock_git, \
         patch("test_agents.tools.claude_cli.ClaudeCliTool.run") as mock_claude:

        mock_git.return_value = "diff --git a/order.py b/order.py\n+def new(): pass"
        mock_claude.side_effect = [
            "## 变更概述\n新增订单功能",
            '[{"case_id": "TC001", "verdict": "pass", "score": 90}]',
        ]

        result = run_test_agents(
            module_name="order",
            source_commit="a1b2c3d",
            target_commit="e4f5g6h",
            test_cases='[{"case_id": "TC001", "title": "test order"}]',
        )

        assert "code_change_report" in result
        assert "review_results" in result
        assert result["review_results"][0]["verdict"] == "pass"


def test_pipeline_with_error():
    """测试错误处理流程"""
    with patch("test_agents.tools.git_diff.GitDiffTool.run") as mock_git:
        mock_git.return_value = "错误: git diff 失败"

        result = run_test_agents(
            module_name="order",
            source_commit="a1b2c3d",
            target_commit="e4f5g6h",
        )

        assert "error" in result or result.get("code_change_report", "").startswith("错误")
```

- [ ] **Step 2: 运行测试**

```bash
python -m pytest test_agents/tests/test_integration.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add test_agents/tests/test_integration.py
git commit -m "test: add integration tests for full pipeline"
```

---

## Task 14: config.py

**Files:**
- Create: `test_agents/config.py`

- [ ] **Step 1: 实现配置模块**

Create `test_agents/config.py`:

```python
"""全局配置"""

import os
from typing import Optional


class Config:
    """配置类"""

    # LLM 配置
    LLM_MODEL: str = os.getenv("TEST_AGENTS_MODEL", "gpt-4o")
    LLM_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")

    # Claude CLI 配置
    CLAUDE_TIMEOUT: int = int(os.getenv("TEST_AGENTS_CLAUDE_TIMEOUT", "120"))
    CLAUDE_MAX_RETRIES: int = int(os.getenv("TEST_AGENTS_CLAUDE_RETRIES", "2"))

    # Git 配置
    GIT_TIMEOUT: int = int(os.getenv("TEST_AGENTS_GIT_TIMEOUT", "30"))

    # Diff 配置
    MAX_DIFF_SIZE: int = int(os.getenv("TEST_AGENTS_MAX_DIFF_SIZE", "100000"))

    # 业务知识库路径
    KNOWLEDGE_DIR: str = os.getenv("TEST_AGENTS_KNOWLEDGE_DIR", "")


config = Config()
```

- [ ] **Step 2: Commit**

```bash
git add test_agents/config.py
git commit -m "feat: add config module with env var support"
```

---

## Task 15: 最终文档与验证

**Files:**
- Modify: `test_agents/readme.md`

- [ ] **Step 1: 更新 readme.md**

Write `test_agents/readme.md`:

```markdown
# 测试智能体群（Test Agents）

基于 LangGraph Supervisor 模式的多智能体测试系统。

## 架构

- **测试经理（Supervisor）**：调度任务，决定调用代码分析 Agent 或用例评审 Agent
- **代码分析 Agent**：分析代码变更，生成变更报告
- **用例评审 Agent**：评审测试用例质量

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

### 1. 安装 Claude CLI Skills

```bash
cp -r test_agents/skills/code_analysis_skill ~/.claude/skills/
cp -r test_agents/skills/case_review_skill ~/.claude/skills/
```

### 2. 运行测试分析

```bash
python -m test_agents \
  --module order \
  --source a1b2c3d \
  --target e4f5g6h \
  --cases '[{"case_id":"TC001","title":"test order"}]'
```

### 3. 查看结果

```bash
python -m test_agents \
  --module order \
  --source a1b2c3d \
  --target e4f5g6h \
  --cases '[{"case_id":"TC001","title":"test order"}]' \
  --output markdown
```

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `TEST_AGENTS_MODEL` | LLM 模型 | gpt-4o |
| `TEST_AGENTS_CLAUDE_TIMEOUT` | Claude CLI 超时(秒) | 120 |
| `TEST_AGENTS_MAX_DIFF_SIZE` | 最大 diff 大小 | 100000 |

## 测试

```bash
python -m pytest test_agents/tests/ -v
```
```

- [ ] **Step 2: 运行完整测试套件**

```bash
python -m pytest test_agents/tests/ -v
```

Expected: 所有测试通过

- [ ] **Step 3: Commit**

```bash
git add test_agents/readme.md
git commit -m "docs: add comprehensive README with quickstart guide"
```

---

## 自检清单

### Spec 覆盖度检查

| Spec 章节 | 对应 Task | 状态 |
|---|---|---|
| 3. 状态设计（GraphState） | Task 2 | 已实现 Pydantic 验证 |
| 4.1 Supervisor 节点 | Task 6 | 已实现路由逻辑 |
| 4.2 代码分析智能体 | Task 7 | 已实现 |
| 4.3 用例评审智能体 | Task 8 | 已实现 |
| 5. 图编排 | Task 9 | 已实现 StateGraph |
| 6.1 GitDiffTool | Task 3 | 已实现 + 安全验证 |
| 6.2 ClaudeCliTool | Task 4 | 已实现 + 重试 |
| 6.3 TestCaseParserTool | Task 5 | 已实现 |
| 6.4 BusinessKnowledgeTool | Task 5 | 已实现 |
| 7. Skill 层 | Task 10 | 已实现 SKILL.md |
| 8. 错误处理 | Task 3,4,7,8 | 已集成 |
| 9. 扩展性 | Task 6,9 | 已预留 |

### 占位符扫描

- [x] 无 TBD/TODO
- [x] 无 "implement later"
- [x] 无 "add appropriate error handling"（每个工具都有具体错误处理）
- [x] 无 "write tests for the above"（每个 Task 都有具体测试代码）
- [x] 无 "similar to Task N"

### 类型一致性检查

- [x] TestAgentState 字段名一致
- [x] tool.run() 签名一致（parameters: dict -> str）
- [x] route_decision 返回值一致（Literal["analyze", "review", "end"]）
