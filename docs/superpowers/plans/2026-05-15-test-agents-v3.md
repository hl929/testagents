# Test Agents v3 (Plan-and-Solve + Reflection) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Test Agents 从 v1 (Supervisor 硬路由) 升级到 v3 (Plan-and-Solve + Reflection)，实现自然语言输入、LLM 规划、Human-in-the-loop 确认、Worker ReAct+反思子图、经验记录。

**Architecture:** 监督者采用 Plan-and-Solve 范式：Planner 解析自然语言生成 ExecutionPlan → ConfirmPlan 中断等待用户确认 → Dispatch 按序路由 Worker 子图 → Reflect 评估整体结果。每个 Worker 是独立的 ReAct+Reflection 子图，作为主图节点注册。支持监督者调度和直接调用 Worker 两种模式。

**Tech Stack:** Python 3.10+, LangGraph >=0.2.0, LangChain-Core >=0.3.0, LangChain-OpenAI >=0.2.0, Pydantic >=2.0.0

---

## File Structure

```
test_agents/
├── agents/
│   ├── __init__.py              # 不变
│   ├── supervisor.py            # 重写: planner_node, confirm_plan_node, dispatch_node, reflect_node, synthesize_node, save_experience_node
│   ├── worker_base.py           # 新建: build_worker_graph, agent_node, worker_reflect, worker_route
│   ├── code_analyzer.py         # 重写: 子图定义 + 状态映射包装
│   └── case_reviewer.py         # 重写: 子图定义 + 状态映射包装
├── tools/
│   ├── __init__.py              # 不变
│   ├── claude_cli.py            # 不变
│   ├── test_case_parser.py      # 不变
│   ├── business_knowledge.py    # 不变
│   └── langchain_adapters.py    # 新建: @tool 包装器
├── graph/
│   ├── __init__.py              # 不变
│   ├── state.py                 # 重写: SupervisorState + WorkerState + Pydantic 模型
│   └── builder.py               # 重写: 主图组装 + 路由函数
├── skills/                      # 不变
├── prompts/
│   ├── loader.py                # 不变
│   ├── code_analyzer.md         # 不变
│   ├── case_reviewer.md         # 不变
│   ├── supervisor.md            # 删除（旧版）
│   ├── planner.md               # 新建
│   ├── supervisor_reflect.md    # 新建
│   ├── synthesize.md            # 新建
│   └── worker_reflect.md        # 新建
├── config.py                    # 更新: 新增 v3 配置项
├── main.py                      # 重写: 自然语言输入 + 双模式
├── data/                        # 新建: 运行时数据目录
│   └── reflection_experience.md # 运行时生成
└── tests/
    ├── test_state.py            # 重写
    ├── test_langchain_adapters.py # 新建
    ├── test_worker_base.py      # 新建
    ├── test_supervisor.py       # 重写
    ├── test_builder.py          # 重写
    ├── test_main.py             # 重写
    ├── test_integration.py      # 重写
    ├── test_claude_cli.py       # 不变
    └── test_tools_misc.py       # 不变
```

---

### Task 1: State Models

**Files:**
- Rewrite: `test_agents/graph/state.py`
- Rewrite: `test_agents/tests/test_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# test_agents/tests/test_state.py
import pytest
from test_agents.graph.state import (
    PlanStep, ExecutionPlan, StepResult, AnalysisTarget,
    SupervisorState, WorkerState,
)


class TestPlanStep:
    def test_create_plan_step(self):
        step = PlanStep(
            step_id=1,
            agent="code_analyzer",
            description="分析 payment 模块代码变更",
            input_mapping={"module_name": "payment", "source_commit": "abc1234", "target_commit": "def5678"},
        )
        assert step.step_id == 1
        assert step.agent == "code_analyzer"
        assert step.input_mapping["module_name"] == "payment"

    def test_input_mapping_default_empty(self):
        step = PlanStep(step_id=1, agent="code_analyzer", description="test")
        assert step.input_mapping == {}


class TestExecutionPlan:
    def test_create_plan(self):
        step = PlanStep(step_id=1, agent="code_analyzer", description="分析代码")
        plan = ExecutionPlan(intent="分析代码变更", steps=[step])
        assert plan.intent == "分析代码变更"
        assert len(plan.steps) == 1
        assert plan.confirmed is False

    def test_plan_serialization_roundtrip(self):
        step = PlanStep(step_id=1, agent="code_analyzer", description="分析代码",
                        input_mapping={"module_name": "payment"})
        plan = ExecutionPlan(intent="分析", steps=[step])
        d = plan.model_dump()
        assert d["steps"][0]["input_mapping"]["module_name"] == "payment"
        restored = ExecutionPlan.model_validate(d)
        assert restored.steps[0].input_mapping["module_name"] == "payment"

    def test_confirmed_default_false(self):
        plan = ExecutionPlan(intent="test", steps=[])
        assert plan.confirmed is False


class TestAnalysisTarget:
    def test_valid_target(self):
        target = AnalysisTarget(
            module_name="payment", source_commit="abc1234", target_commit="def5678"
        )
        assert target.module_name == "payment"
        assert target.source_commit == "abc1234"

    def test_invalid_commit_sha(self):
        with pytest.raises(ValueError, match="Invalid commit SHA"):
            AnalysisTarget(module_name="payment", source_commit="invalid!", target_commit="def5678")

    def test_path_traversal_module(self):
        with pytest.raises(ValueError, match="Invalid module name"):
            AnalysisTarget(module_name="../../etc", source_commit="abc1234", target_commit="def5678")

    def test_commit_sha_normalized_lowercase(self):
        target = AnalysisTarget(module_name="pay", source_commit="ABC1234", target_commit="DEF5678")
        assert target.source_commit == "abc1234"

    def test_default_commit_msg(self):
        target = AnalysisTarget(module_name="pay", source_commit="abc1234", target_commit="def5678")
        assert target.commit_msg == ""


class TestStepResult:
    def test_create_step_result(self):
        result = StepResult(step_id=1, agent="code_analyzer", status="success", output_key="code_change_report")
        assert result.status == "success"
        assert result.error == ""

    def test_failed_step_result(self):
        result = StepResult(step_id=1, agent="code_analyzer", status="failed", output_key="code_change_report", error="timeout")
        assert result.status == "failed"
        assert result.error == "timeout"


class TestWorkerState:
    def test_worker_state_is_dict(self):
        state: WorkerState = {
            "task": "分析代码",
            "messages": [],
            "error": "no",
            "reflection_count": 0,
            "max_reflections": 0,
            "result": "",
            "output_key": "code_change_report",
        }
        assert state["task"] == "分析代码"
        assert state["error"] == "no"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_state.py -v`
Expected: FAIL — ImportError (new model names not defined yet)

- [ ] **Step 3: Write the implementation**

```python
# test_agents/graph/state.py
"""State definitions for Test Agents v3 - Plan-and-Solve + Reflection"""

import operator
import re
from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import AnyMessage, add_messages
from pydantic import BaseModel, Field, field_validator


class PlanStep(BaseModel):
    step_id: int = Field(description="步骤序号，从 1 开始")
    agent: str = Field(description="执行 agent: code_analyzer / case_reviewer")
    description: str = Field(description="步骤描述")
    input_mapping: dict[str, str] = Field(default_factory=dict, description="agent入参 → state字段引用或常量")


class ExecutionPlan(BaseModel):
    intent: str = Field(description="用户意图摘要")
    steps: list[PlanStep] = Field(default_factory=list, description="有序步骤列表")
    confirmed: bool = Field(default=False, description="用户是否确认")


class StepResult(BaseModel):
    step_id: int = Field(description="步骤序号")
    agent: str = Field(description="执行 agent")
    status: str = Field(description="success / failed")
    output_key: str = Field(description="结果写入主图 state 的哪个字段")
    error: str = Field(default="", description="错误信息")


class AnalysisTarget(BaseModel):
    module_name: str = Field(description="模块名称")
    source_commit: str = Field(description="源 commit SHA")
    target_commit: str = Field(description="目标 commit SHA")
    commit_msg: str = Field(default="", description="commit message")

    @field_validator("source_commit", "target_commit")
    @classmethod
    def validate_commit_sha(cls, value: str) -> str:
        if not value:
            return value
        if not re.match(r"^[a-f0-9]{7,40}$", value, re.IGNORECASE):
            raise ValueError(f"Invalid commit SHA: {value}. Must be 7-40 hex characters.")
        return value.lower()

    @field_validator("module_name")
    @classmethod
    def validate_module_name(cls, value: str) -> str:
        if not value:
            return value
        if ".." in value or value.startswith("/"):
            raise ValueError(f"Invalid module name: {value}")
        return value


class SupervisorState(TypedDict, total=False):
    user_request: str
    targets: list[dict]
    test_cases: list[dict]
    business_knowledge: str
    plan: Optional[dict]
    current_step_index: int
    step_results: Annotated[list, operator.add]
    needs_replan: bool
    reflection_feedback: Optional[str]
    max_plan_iterations: int
    plan_iterations: int
    confirm_retry_count: int
    max_confirm_retries: int
    code_change_report: str
    review_results: list[dict]
    final_answer: Optional[str]
    messages: Annotated[list[AnyMessage], add_messages]


class WorkerState(TypedDict, total=False):
    task: str
    messages: Annotated[list[AnyMessage], add_messages]
    error: str
    reflection_count: int
    max_reflections: int
    result: str
    output_key: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_state.py -v`
Expected: PASS (all 10 tests)

- [ ] **Step 5: Commit**

```bash
git add test_agents/graph/state.py test_agents/tests/test_state.py
git commit -m "feat: rewrite state models for Plan-and-Solve + Reflection v3 architecture"
```

---

### Task 2: Config Update & Data Directory

**Files:**
- Modify: `test_agents/config.py`
- Create: `test_agents/data/.gitkeep`

- [ ] **Step 1: Write the failing test**

```python
# Add to test_agents/tests/test_state.py (or create test_agents/tests/test_config.py)
from test_agents.config import config


def test_config_has_v3_fields():
    assert hasattr(config, "MAX_PLAN_ITERATIONS")
    assert config.MAX_PLAN_ITERATIONS == 1
    assert hasattr(config, "MAX_CONFIRM_RETRIES")
    assert config.MAX_CONFIRM_RETRIES == 3
    assert hasattr(config, "MAX_WORKER_REFLECTIONS")
    assert config.MAX_WORKER_REFLECTIONS == 0
    assert hasattr(config, "EXPERIENCE_FILE")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_config.py -v`
Expected: FAIL — AttributeError

- [ ] **Step 3: Write the implementation**

```python
# test_agents/config.py
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

    # 业务知识库路径
    KNOWLEDGE_DIR: str = os.getenv("TEST_AGENTS_KNOWLEDGE_DIR", "")

    # v3 Plan-and-Solve + Reflection 配置
    MAX_PLAN_ITERATIONS: int = int(os.getenv("TEST_AGENTS_MAX_PLAN_ITERATIONS", "1"))
    MAX_CONFIRM_RETRIES: int = int(os.getenv("TEST_AGENTS_MAX_CONFIRM_RETRIES", "3"))
    MAX_WORKER_REFLECTIONS: int = int(os.getenv("TEST_AGENTS_MAX_WORKER_REFLECTIONS", "0"))
    EXPERIENCE_FILE: str = os.getenv(
        "TEST_AGENTS_EXPERIENCE_FILE",
        os.path.join(os.path.dirname(__file__), "data", "reflection_experience.md"),
    )


config = Config()
```

Create data directory:

```bash
mkdir -p test_agents/data && touch test_agents/data/.gitkeep
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/config.py test_agents/tests/test_config.py test_agents/data/.gitkeep
git commit -m "feat: add v3 config fields and data directory"
```

---

### Task 3: LangChain Tool Adapters

**Files:**
- Create: `test_agents/tools/langchain_adapters.py`
- Create: `test_agents/tests/test_langchain_adapters.py`

- [ ] **Step 1: Write the failing tests**

```python
# test_agents/tests/test_langchain_adapters.py
import json
from unittest.mock import patch, MagicMock

from test_agents.tools.langchain_adapters import claude_cli, parse_test_cases, query_business_knowledge


def test_claude_cli_adapter_invocation():
    with patch("test_agents.tools.langchain_adapters.ClaudeCliTool") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.run.return_value = "analysis result"
        mock_cls.return_value = mock_instance
        result = claude_cli.invoke({"prompt": "test prompt"})
        assert result == "analysis result"
        mock_instance.run.assert_called_once_with({"prompt": "test prompt", "model": ""})


def test_parse_test_cases_adapter_json():
    result = parse_test_cases.invoke({"input_data": '[{"case_id": "TC001", "title": "test"}]', "input_format": "json"})
    parsed = json.loads(result)
    assert len(parsed) == 1
    assert parsed[0]["case_id"] == "TC001"


def test_parse_test_cases_adapter_text():
    result = parse_test_cases.invoke({"input_data": "Test case 1\nTest case 2", "input_format": "text"})
    parsed = json.loads(result)
    assert len(parsed) == 2
    assert parsed[0]["case_id"] == "TC001"


def test_query_business_knowledge_adapter():
    result = query_business_knowledge.invoke({"module_name": "nonexistent_module"})
    assert result == ""


def test_tools_are_langchain_tools():
    from langchain_core.tools import BaseTool
    assert isinstance(claude_cli, BaseTool)
    assert isinstance(parse_test_cases, BaseTool)
    assert isinstance(query_business_knowledge, BaseTool)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_langchain_adapters.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Write the implementation**

```python
# test_agents/tools/langchain_adapters.py
"""LangChain tool adapters - wraps existing tools as @tool functions"""

import json

from langchain_core.tools import tool

from test_agents.tools.claude_cli import ClaudeCliTool
from test_agents.tools.test_case_parser import TestCaseParserTool
from test_agents.tools.business_knowledge import BusinessKnowledgeTool


@tool
def claude_cli(prompt: str, model: str = "") -> str:
    """调用 Claude CLI 执行分析任务。prompt 为完整提示词，model 为可选模型名。"""
    return ClaudeCliTool().run({"prompt": prompt, "model": model})


@tool
def parse_test_cases(input_data: str, input_format: str = "json") -> str:
    """解析测试用例输入为结构化列表。input_data 为原始数据，input_format 为 json 或 text。"""
    result = TestCaseParserTool().run({"input_data": input_data, "format": input_format})
    return json.dumps(result, ensure_ascii=False)


@tool
def query_business_knowledge(module_name: str) -> str:
    """查询模块相关的业务知识。module_name 为模块名称。"""
    return BusinessKnowledgeTool().run({"module_name": module_name})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_langchain_adapters.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add test_agents/tools/langchain_adapters.py test_agents/tests/test_langchain_adapters.py
git commit -m "feat: add LangChain tool adapters for worker subgraph integration"
```

---

### Task 4: Prompt Templates

**Files:**
- Create: `test_agents/prompts/planner.md`
- Create: `test_agents/prompts/supervisor_reflect.md`
- Create: `test_agents/prompts/synthesize.md`
- Create: `test_agents/prompts/worker_reflect.md`
- Delete: `test_agents/prompts/supervisor.md`

- [ ] **Step 1: Write the failing test**

```python
# test_agents/tests/test_prompts.py
from test_agents.prompts.loader import load_prompt


def test_planner_prompt_loads():
    prompt = load_prompt("planner", user_request="分析 payment 模块代码变更")
    assert "payment" in prompt
    assert "code_analyzer" in prompt


def test_supervisor_reflect_prompt_loads():
    prompt = load_prompt("supervisor_reflect", user_request="test", plan_summary="plan", step_results_summary="results")
    assert "COMPLETE" in prompt or "REPLAN" in prompt


def test_synthesize_prompt_loads():
    prompt = load_prompt("synthesize", user_request="test", plan_summary="plan", step_results_summary="results")
    assert "test" in prompt


def test_worker_reflect_prompt_loads():
    prompt = load_prompt("worker_reflect", task="分析代码", result="报告内容")
    assert "pass" in prompt or "retry" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_prompts.py -v`
Expected: FAIL — FileNotFoundError

- [ ] **Step 3: Write the prompt templates**

```markdown
<!-- test_agents/prompts/planner.md -->
你是测试规划专家。根据用户的自然语言需求，生成结构化的执行计划。

## 可用 Agent

| Agent | 能力 | 必需入参 | 产出字段 |
|---|---|---|---|
| `code_analyzer` | 分析代码变更 | module_name, source_commit, target_commit | code_change_report |
| `case_reviewer` | 评审测试用例 | code_change_report, test_cases, business_knowledge | review_results |

## 输入

用户需求：{user_request}

## 输出格式

请输出严格的 JSON 格式：
```json
{{{{
  "intent": "用户意图摘要",
  "steps": [
    {{{{
      "step_id": 1,
      "agent": "code_analyzer 或 case_reviewer",
      "description": "步骤描述",
      "input_mapping": {{{{
        "参数名": "常量值 或 ${{{{state字段名}}}}"
      }}}}
    }}}}
  ],
  "confirmed": false
}}}}
```

## 规则

1. 根据用户意图选择最少步骤组合
2. 多模块时为每个模块生成一个 code_analyzer 步骤
3. case_reviewer 需要在 code_analyzer 之后执行（依赖 code_change_report）
4. input_mapping 中常量直接写值，state 引用用 ${{{{字段名}}}} 格式
5. 如果用户意图不明确，在 intent 中说明需要补充的信息
```

```markdown
<!-- test_agents/prompts/supervisor_reflect.md -->
你是测试监督者，负责评估整体执行结果。

## 用户原始需求
{user_request}

## 执行计划
{plan_summary}

## 执行结果
{step_results_summary}

## 评估要求

请评估：执行计划的所有步骤是否完整正确地解决了用户的原始需求？

输出格式（严格 JSON）：
```json
{{{{
  "assessment": "COMPLETE 或 REPLAN",
  "feedback": "评估反馈，如果 REPLAN 请说明需要重新规划的原因"
}}}}
```

如果结果完整正确，输出 COMPLETE。如果需要重新规划，输出 REPLAN 并说明原因。
```

```markdown
<!-- test_agents/prompts/synthesize.md -->
你是结果汇总专家。请基于以下执行结果，综合回答用户的原始需求。

## 用户原始需求
{user_request}

## 执行计划
{plan_summary}

## 各步骤结果
{step_results_summary}

## 输出要求

请生成最终的综合分析报告，直接回答用户需求。报告应包含：
1. 需求理解摘要
2. 各步骤关键发现
3. 综合结论和建议
```

```markdown
<!-- test_agents/prompts/worker_reflect.md -->
你是结果质量评估专家。请评估以下执行结果的质量。

## 任务描述
{task}

## 执行结果
{result}

## 评估要求

请评估执行结果是否完整、准确、高质量地完成了任务。

输出格式（严格 JSON）：
```json
{{{{
  "quality": "pass 或 retry",
  "feedback": "质量评估反馈，如果 retry 请说明需要改进的地方"
}}}}
```

如果结果质量合格，输出 pass。如果需要重试，输出 retry 并说明改进建议。
```

Delete old supervisor prompt:

```bash
rm test_agents/prompts/supervisor.md
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_prompts.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add test_agents/prompts/planner.md test_agents/prompts/supervisor_reflect.md test_agents/prompts/synthesize.md test_agents/prompts/worker_reflect.md test_agents/tests/test_prompts.py
git rm test_agents/prompts/supervisor.md
git commit -m "feat: add v3 prompt templates (planner, reflect, synthesize, worker_reflect)"
```

---

### Task 5: Worker Subgraph Factory

**Files:**
- Create: `test_agents/agents/worker_base.py`
- Create: `test_agents/tests/test_worker_base.py`

- [ ] **Step 1: Write the failing tests**

```python
# test_agents/tests/test_worker_base.py
import pytest
from unittest.mock import MagicMock, patch

from test_agents.agents.worker_base import worker_route, build_worker_graph
from test_agents.graph.state import WorkerState


class TestWorkerRoute:
    def test_error_no_returns_end(self):
        state: WorkerState = {"error": "no", "reflection_count": 0, "max_reflections": 1}
        assert worker_route(state) == "__end__"

    def test_error_yes_under_limit_returns_agent(self):
        state: WorkerState = {"error": "yes", "reflection_count": 0, "max_reflections": 2}
        assert worker_route(state) == "agent"

    def test_error_yes_at_limit_returns_end(self):
        state: WorkerState = {"error": "yes", "reflection_count": 2, "max_reflections": 2}
        assert worker_route(state) == "__end__"

    def test_error_yes_over_limit_returns_end(self):
        state: WorkerState = {"error": "yes", "reflection_count": 3, "max_reflections": 2}
        assert worker_route(state) == "__end__"

    def test_max_reflections_zero_always_end(self):
        state: WorkerState = {"error": "yes", "reflection_count": 0, "max_reflections": 0}
        assert worker_route(state) == "__end__"


class TestBuildWorkerGraph:
    def test_builds_graph_with_tools(self):
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"

        graph = build_worker_graph([mock_tool], mock_llm, mock_llm_with_tools)
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"

        graph = build_worker_graph([mock_tool], mock_llm, mock_llm_with_tools)
        node_names = set(graph.get_graph().nodes.keys())
        assert "agent" in node_names
        assert "tools" in node_names
        assert "reflect" in node_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_worker_base.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Write the implementation**

```python
# test_agents/agents/worker_base.py
"""Worker subgraph factory - ReAct + Reflection pattern"""

import json
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from test_agents.graph.state import WorkerState
from test_agents.prompts.loader import load_prompt


def agent_node(state: WorkerState, llm_with_tools) -> dict:
    """Worker agent node - LLM with tool binding"""
    messages = state.get("messages", [])
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def worker_reflect(state: WorkerState, llm) -> dict:
    """Worker reflect node - evaluate result quality"""
    max_reflections = state.get("max_reflections", 0)
    if max_reflections == 0:
        return {"error": "no"}

    reflection_count = state.get("reflection_count", 0)
    if reflection_count >= max_reflections:
        return {"error": "no"}

    result = state.get("result", "")
    messages = state.get("messages", [])
    if not result and messages:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                result = msg.content
                break

    task = state.get("task", "")
    prompt = load_prompt("worker_reflect", task=task, result=result[:2000])
    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        assessment = json.loads(content)
        if assessment.get("quality") == "pass":
            return {"error": "no"}
        feedback = assessment.get("feedback", "")
        return {
            "error": "yes",
            "reflection_count": reflection_count + 1,
            "messages": [HumanMessage(content=f"质量评估不通过，请重试。反馈：{feedback}")],
        }
    except (json.JSONDecodeError, AttributeError, IndexError):
        return {"error": "no"}


def worker_route(state: WorkerState) -> Literal["agent", "__end__"]:
    """Route after reflect: retry or end"""
    if state.get("error") == "no":
        return "__end__"
    if state.get("reflection_count", 0) >= state.get("max_reflections", 0):
        return "__end__"
    return "agent"


def build_worker_graph(tools: list, llm, llm_with_tools):
    """Build a ReAct + Reflection Worker subgraph"""
    def agent_node_bound(state: WorkerState) -> dict:
        return agent_node(state, llm_with_tools)

    def worker_reflect_bound(state: WorkerState) -> dict:
        return worker_reflect(state, llm)

    graph = StateGraph(WorkerState)
    graph.add_node("agent", agent_node_bound)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("reflect", worker_reflect_bound)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", "__end__": "reflect"})
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("reflect", worker_route, {"agent": "agent", "__end__": END})

    return graph.compile()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_worker_base.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add test_agents/agents/worker_base.py test_agents/tests/test_worker_base.py
git commit -m "feat: add worker subgraph factory with ReAct + Reflection pattern"
```

---

### Task 6: Worker Definitions (code_analyzer + case_reviewer)

**Files:**
- Rewrite: `test_agents/agents/code_analyzer.py`
- Rewrite: `test_agents/agents/case_reviewer.py`
- Create: `test_agents/tests/test_workers.py`

- [ ] **Step 1: Write the failing tests**

```python
# test_agents/tests/test_workers.py
from unittest.mock import MagicMock, patch

from test_agents.agents.code_analyzer import build_code_analyzer_graph, code_analyzer_wrapper
from test_agents.agents.case_reviewer import build_case_reviewer_graph, case_reviewer_wrapper
from test_agents.graph.state import SupervisorState


class TestCodeAnalyzerGraph:
    def test_builds_code_analyzer_graph(self):
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        graph = build_code_analyzer_graph(mock_llm, mock_llm_with_tools)
        assert graph is not None

    def test_code_analyzer_wrapper_returns_report(self):
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "result": "## 变更概述\n新增订单功能",
            "messages": [],
            "error": "no",
        }
        state: SupervisorState = {
            "user_request": "分析代码",
            "plan": {
                "intent": "分析代码变更",
                "steps": [
                    {"step_id": 1, "agent": "code_analyzer", "description": "分析 payment 模块",
                     "input_mapping": {"module_name": "payment", "source_commit": "abc1234", "target_commit": "def5678"}},
                ],
                "confirmed": True,
            },
            "current_step_index": 0,
            "step_results": [],
            "messages": [],
        }
        with patch("test_agents.agents.code_analyzer.code_analyzer_graph", mock_graph):
            result = code_analyzer_wrapper(state)
        assert "code_change_report" in result
        assert "变更概述" in result["code_change_report"]
        assert result["current_step_index"] == 1


class TestCaseReviewerGraph:
    def test_builds_case_reviewer_graph(self):
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        graph = build_case_reviewer_graph(mock_llm, mock_llm_with_tools)
        assert graph is not None

    def test_case_reviewer_wrapper_returns_results(self):
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "result": '[{"case_id": "TC001", "verdict": "pass"}]',
            "messages": [],
            "error": "no",
        }
        state: SupervisorState = {
            "user_request": "评审用例",
            "plan": {
                "intent": "评审测试用例",
                "steps": [
                    {"step_id": 2, "agent": "case_reviewer", "description": "评审用例",
                     "input_mapping": {"code_change_report": "${code_change_report}"}},
                ],
                "confirmed": True,
            },
            "current_step_index": 0,
            "code_change_report": "变更报告",
            "step_results": [],
            "messages": [],
        }
        with patch("test_agents.agents.case_reviewer.case_reviewer_graph", mock_graph):
            result = case_reviewer_wrapper(state)
        assert "review_results" in result
        assert result["current_step_index"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_workers.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Write the implementation**

```python
# test_agents/agents/code_analyzer.py
"""Code analyzer worker - ReAct subgraph with ClaudeCliTool"""

import json
from langchain_core.messages import HumanMessage

from test_agents.agents.worker_base import build_worker_graph
from test_agents.graph.state import SupervisorState, WorkerState
from test_agents.tools.langchain_adapters import claude_cli


_code_analyzer_tools = [claude_cli]
code_analyzer_graph = None


def build_code_analyzer_graph(llm, llm_with_tools):
    """Build and cache the code analyzer subgraph"""
    global code_analyzer_graph
    code_analyzer_graph = build_worker_graph(_code_analyzer_tools, llm, llm_with_tools)
    return code_analyzer_graph


def _resolve_input(value: str, state: SupervisorState) -> str:
    """Resolve input_mapping value: ${field} → state field, otherwise constant"""
    if value.startswith("${") and value.endswith("}"):
        field_name = value[2:-1]
        val = state.get(field_name, "")
        return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
    return value


def code_analyzer_wrapper(state: SupervisorState) -> dict:
    """Code analyzer node - transforms SupervisorState, invokes subgraph, maps result back"""
    plan = state.get("plan") or {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    current_index = state.get("current_step_index", 0)

    if current_index >= len(steps):
        return {"current_step_index": current_index}

    step = steps[current_index]
    input_mapping = step.get("input_mapping", {})

    module_name = _resolve_input(input_mapping.get("module_name", ""), state)
    source_commit = _resolve_input(input_mapping.get("source_commit", ""), state)
    target_commit = _resolve_input(input_mapping.get("target_commit", ""), state)

    task_desc = step.get("description", "")
    worker_input: WorkerState = {
        "task": task_desc,
        "messages": [HumanMessage(content=f"分析模块 {module_name} 的代码变更，commit 范围: {source_commit}..{target_commit}")],
        "error": "no",
        "reflection_count": 0,
        "max_reflections": 0,
        "output_key": "code_change_report",
        "result": "",
    }

    if code_analyzer_graph is None:
        raise RuntimeError("code_analyzer_graph not initialized. Call build_code_analyzer_graph first.")

    result = code_analyzer_graph.invoke(worker_input)

    report = result.get("result", "")
    if not report:
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content and not msg.tool_calls if hasattr(msg, "tool_calls") else True:
                if hasattr(msg, "content") and not getattr(msg, "tool_calls", None):
                    report = msg.content
                    break

    existing_report = state.get("code_change_report", "")
    if existing_report and module_name:
        report = existing_report + f"\n\n## 模块: {module_name}\n" + report

    return {
        "code_change_report": report,
        "current_step_index": current_index + 1,
        "step_results": [{
            "step_id": step.get("step_id", 0),
            "agent": step.get("agent", ""),
            "status": "success" if report else "failed",
            "output_key": "code_change_report",
            "error": "" if report else "Empty result",
        }],
    }
```

```python
# test_agents/agents/case_reviewer.py
"""Case reviewer worker - ReAct subgraph with ClaudeCliTool + TestCaseParserTool + BusinessKnowledgeTool"""

import json
from langchain_core.messages import HumanMessage

from test_agents.agents.worker_base import build_worker_graph
from test_agents.graph.state import SupervisorState, WorkerState
from test_agents.tools.langchain_adapters import claude_cli, parse_test_cases, query_business_knowledge


_case_reviewer_tools = [claude_cli, parse_test_cases, query_business_knowledge]
case_reviewer_graph = None


def build_case_reviewer_graph(llm, llm_with_tools):
    """Build and cache the case reviewer subgraph"""
    global case_reviewer_graph
    case_reviewer_graph = build_worker_graph(_case_reviewer_tools, llm, llm_with_tools)
    return case_reviewer_graph


def _resolve_input(value: str, state: SupervisorState) -> str:
    """Resolve input_mapping value: ${field} → state field, otherwise constant"""
    if value.startswith("${") and value.endswith("}"):
        field_name = value[2:-1]
        val = state.get(field_name, "")
        return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
    return value


def case_reviewer_wrapper(state: SupervisorState) -> dict:
    """Case reviewer node - transforms SupervisorState, invokes subgraph, maps result back"""
    plan = state.get("plan") or {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    current_index = state.get("current_step_index", 0)

    if current_index >= len(steps):
        return {"current_step_index": current_index}

    step = steps[current_index]
    input_mapping = step.get("input_mapping", {})

    code_change_report = _resolve_input(input_mapping.get("code_change_report", ""), state)
    test_cases_raw = _resolve_input(input_mapping.get("test_cases", ""), state)
    business_knowledge = _resolve_input(input_mapping.get("business_knowledge", ""), state)

    task_desc = step.get("description", "")
    context_parts = [task_desc]
    if code_change_report:
        context_parts.append(f"代码变更报告:\n{code_change_report[:3000]}")
    if test_cases_raw:
        context_parts.append(f"测试用例:\n{test_cases_raw[:2000]}")
    if business_knowledge:
        context_parts.append(f"业务知识:\n{business_knowledge[:1000]}")

    worker_input: WorkerState = {
        "task": task_desc,
        "messages": [HumanMessage(content="\n\n".join(context_parts))],
        "error": "no",
        "reflection_count": 0,
        "max_reflections": 0,
        "output_key": "review_results",
        "result": "",
    }

    if case_reviewer_graph is None:
        raise RuntimeError("case_reviewer_graph not initialized. Call build_case_reviewer_graph first.")

    result = case_reviewer_graph.invoke(worker_input)

    review_text = result.get("result", "")
    if not review_text:
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                review_text = msg.content
                break

    review_results = []
    try:
        if "```json" in review_text:
            json_str = review_text.split("```json")[1].split("```")[0].strip()
        elif "```" in review_text:
            json_str = review_text.split("```")[1].split("```")[0].strip()
        else:
            json_str = review_text
        review_results = json.loads(json_str)
        if not isinstance(review_results, list):
            review_results = [review_results]
    except (json.JSONDecodeError, IndexError):
        review_results = [{"case_id": "N/A", "verdict": "parse_error", "raw": review_text[:500]}]

    return {
        "review_results": review_results,
        "current_step_index": current_index + 1,
        "step_results": [{
            "step_id": step.get("step_id", 0),
            "agent": step.get("agent", ""),
            "status": "success" if review_results else "failed",
            "output_key": "review_results",
            "error": "" if review_results else "Empty result",
        }],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_workers.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add test_agents/agents/code_analyzer.py test_agents/agents/case_reviewer.py test_agents/tests/test_workers.py
git commit -m "feat: rewrite worker definitions as ReAct subgraphs with state mapping wrappers"
```

---

### Task 7: Supervisor Nodes

**Files:**
- Rewrite: `test_agents/agents/supervisor.py`
- Rewrite: `test_agents/tests/test_supervisor.py`

- [ ] **Step 1: Write the failing tests**

```python
# test_agents/tests/test_supervisor.py
import json
from unittest.mock import MagicMock, patch

from test_agents.agents.supervisor import (
    planner_node,
    confirm_plan_node,
    dispatch_node,
    reflect_node,
    synthesize_node,
    save_experience_node,
    route_from_confirm,
    route_from_dispatch,
    route_from_reflect,
)
from test_agents.graph.state import SupervisorState, ExecutionPlan


class TestRouteFromConfirm:
    def test_confirmed_dispatches(self):
        state: SupervisorState = {"plan": {"confirmed": True, "intent": "test", "steps": []}}
        assert route_from_confirm(state) == "dispatch"

    def test_rejected_under_limit_goes_planner(self):
        state: SupervisorState = {
            "plan": {"confirmed": False, "intent": "test", "steps": []},
            "confirm_retry_count": 0,
            "max_confirm_retries": 3,
        }
        assert route_from_confirm(state) == "planner"

    def test_rejected_over_limit_goes_end(self):
        state: SupervisorState = {
            "plan": {"confirmed": False, "intent": "test", "steps": []},
            "confirm_retry_count": 3,
            "max_confirm_retries": 3,
        }
        assert route_from_confirm(state) == "end"


class TestRouteFromDispatch:
    def test_all_steps_done_goes_reflect(self):
        state: SupervisorState = {
            "plan": {"steps": [{"step_id": 1}, {"step_id": 2}]},
            "current_step_index": 2,
        }
        assert route_from_dispatch(state) == "reflect"

    def test_first_step_code_analyzer(self):
        state: SupervisorState = {
            "plan": {"steps": [{"step_id": 1, "agent": "code_analyzer"}, {"step_id": 2, "agent": "case_reviewer"}]},
            "current_step_index": 0,
        }
        assert route_from_dispatch(state) == "code_analyzer"

    def test_second_step_case_reviewer(self):
        state: SupervisorState = {
            "plan": {"steps": [{"step_id": 1, "agent": "code_analyzer"}, {"step_id": 2, "agent": "case_reviewer"}]},
            "current_step_index": 1,
        }
        assert route_from_dispatch(state) == "case_reviewer"


class TestRouteFromReflect:
    def test_needs_replan_under_limit_goes_planner(self):
        state: SupervisorState = {
            "needs_replan": True,
            "plan_iterations": 0,
            "max_plan_iterations": 2,
        }
        assert route_from_reflect(state) == "planner"

    def test_needs_replan_at_limit_goes_synthesize(self):
        state: SupervisorState = {
            "needs_replan": True,
            "plan_iterations": 2,
            "max_plan_iterations": 2,
        }
        assert route_from_reflect(state) == "synthesize"

    def test_complete_goes_synthesize(self):
        state: SupervisorState = {
            "needs_replan": False,
            "plan_iterations": 0,
            "max_plan_iterations": 1,
        }
        assert route_from_reflect(state) == "synthesize"


class TestPlannerNode:
    def test_planner_generates_plan(self):
        mock_llm = MagicMock()
        plan_dict = ExecutionPlan(
            intent="分析代码变更",
            steps=[{"step_id": 1, "agent": "code_analyzer", "description": "分析代码", "input_mapping": {}}],
        ).model_dump()
        mock_llm.with_structured_output.return_value.invoke.return_value = plan_dict

        state: SupervisorState = {"user_request": "分析 payment 模块代码变更", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = planner_node(state)
        assert "plan" in result
        assert result["plan"]["intent"] == "分析代码变更"


class TestConfirmPlanNode:
    def test_confirm_plan_interrupts(self):
        state: SupervisorState = {
            "plan": {"intent": "test", "steps": [{"step_id": 1, "agent": "code_analyzer", "description": "分析代码", "input_mapping": {}}], "confirmed": False},
            "confirm_retry_count": 0,
            "max_confirm_retries": 3,
        }
        with patch("test_agents.agents.supervisor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {"confirmed": True}
            result = confirm_plan_node(state)
        assert result["plan"]["confirmed"] is True

    def test_confirm_plan_rejected_increments_retry(self):
        state: SupervisorState = {
            "plan": {"intent": "test", "steps": [], "confirmed": False},
            "confirm_retry_count": 0,
            "max_confirm_retries": 3,
        }
        with patch("test_agents.agents.supervisor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {"confirmed": False, "feedback": "请修改"}
            result = confirm_plan_node(state)
        assert result["confirm_retry_count"] == 1


class TestDispatchNode:
    def test_dispatch_returns_empty_for_routing(self):
        state: SupervisorState = {
            "plan": {"steps": [{"step_id": 1, "agent": "code_analyzer"}]},
            "current_step_index": 0,
        }
        result = dispatch_node(state)
        assert result == {}


class TestReflectNode:
    def test_reflect_complete(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"assessment": "COMPLETE", "feedback": ""}')
        state: SupervisorState = {
            "user_request": "test",
            "plan": {"intent": "test", "steps": []},
            "step_results": [{"step_id": 1, "status": "success"}],
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = reflect_node(state)
        assert result["needs_replan"] is False

    def test_reflect_replan(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"assessment": "REPLAN", "feedback": "结果不完整"}')
        state: SupervisorState = {
            "user_request": "test",
            "plan": {"intent": "test", "steps": []},
            "step_results": [],
            "messages": [],
            "plan_iterations": 0,
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = reflect_node(state)
        assert result["needs_replan"] is True
        assert result["plan_iterations"] == 1


class TestSynthesizeNode:
    def test_synthesize_generates_answer(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="综合分析报告内容")
        state: SupervisorState = {
            "user_request": "test",
            "plan": {"intent": "test", "steps": []},
            "step_results": [{"step_id": 1, "status": "success"}],
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = synthesize_node(state)
        assert result["final_answer"] == "综合分析报告内容"


class TestSaveExperienceNode:
    def test_save_experience_creates_file(self, tmp_path):
        experience_file = str(tmp_path / "experience.md")
        state: SupervisorState = {
            "user_request": "test",
            "plan": {"intent": "test", "steps": []},
            "step_results": [],
            "reflection_feedback": "",
        }
        with patch("test_agents.agents.supervisor.config") as mock_config:
            mock_config.EXPERIENCE_FILE = experience_file
            result = save_experience_node(state)
        assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_supervisor.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Write the implementation**

```python
# test_agents/agents/supervisor.py
"""Supervisor nodes for Plan-and-Solve + Reflection architecture"""

import json
import os
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from test_agents.config import config
from test_agents.graph.state import SupervisorState, ExecutionPlan
from test_agents.prompts.loader import load_prompt


def get_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=config.LLM_MODEL, api_key=config.LLM_API_KEY)


def planner_node(state: SupervisorState) -> dict:
    """Parse user_request and generate ExecutionPlan"""
    llm = get_llm()
    user_request = state.get("user_request", "")
    prompt = load_prompt("planner", user_request=user_request)

    structured_llm = llm.with_structured_output(ExecutionPlan)
    plan = structured_llm.invoke([HumanMessage(content=prompt)])

    if isinstance(plan, ExecutionPlan):
        plan_dict = plan.model_dump()
    elif isinstance(plan, dict):
        plan_dict = plan
    else:
        plan_dict = {"intent": "解析失败", "steps": [], "confirmed": False}

    return {
        "plan": plan_dict,
        "plan_iterations": state.get("plan_iterations", 0) + 1,
    }


def confirm_plan_node(state: SupervisorState) -> dict:
    """Interrupt for user plan confirmation"""
    plan = state.get("plan", {})
    response = interrupt({
        "type": "confirm_plan",
        "plan": plan,
    })

    if response.get("confirmed", False):
        plan["confirmed"] = True
        return {"plan": plan}
    else:
        feedback = response.get("feedback", "")
        return {
            "confirm_retry_count": state.get("confirm_retry_count", 0) + 1,
            "messages": [HumanMessage(content=f"用户拒绝了计划，反馈：{feedback}")],
        }


def dispatch_node(state: SupervisorState) -> dict:
    """Dispatch hub - routes to workers or reflect based on current_step_index"""
    return {}


def reflect_node(state: SupervisorState) -> dict:
    """Supervisor reflect - evaluate overall results"""
    llm = get_llm()
    user_request = state.get("user_request", "")
    plan = state.get("plan", {})
    step_results = state.get("step_results", [])

    plan_summary = json.dumps(plan.get("steps", []), ensure_ascii=False)
    step_results_summary = json.dumps(step_results, ensure_ascii=False)

    prompt = load_prompt(
        "supervisor_reflect",
        user_request=user_request,
        plan_summary=plan_summary,
        step_results_summary=step_results_summary,
    )

    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        assessment = json.loads(content)

        if assessment.get("assessment") == "REPLAN":
            return {
                "needs_replan": True,
                "plan_iterations": state.get("plan_iterations", 0) + 1,
                "reflection_feedback": assessment.get("feedback", ""),
            }
        else:
            return {
                "needs_replan": False,
                "reflection_feedback": assessment.get("feedback", ""),
            }
    except (json.JSONDecodeError, AttributeError, IndexError):
        return {"needs_replan": False, "reflection_feedback": "反思评估解析失败，默认完成"}


def synthesize_node(state: SupervisorState) -> dict:
    """Synthesize all step results into final answer"""
    llm = get_llm()
    user_request = state.get("user_request", "")
    plan = state.get("plan", {})
    step_results = state.get("step_results", [])

    plan_summary = json.dumps(plan.get("steps", []), ensure_ascii=False)
    step_results_summary = json.dumps(step_results, ensure_ascii=False)

    prompt = load_prompt(
        "synthesize",
        user_request=user_request,
        plan_summary=plan_summary,
        step_results_summary=step_results_summary,
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"final_answer": response.content}


def save_experience_node(state: SupervisorState) -> dict:
    """Save planning and execution experience to file"""
    user_request = state.get("user_request", "")
    plan = state.get("plan", {})
    step_results = state.get("step_results", [])
    reflection_feedback = state.get("reflection_feedback", "")

    experience_file = config.EXPERIENCE_FILE
    os.makedirs(os.path.dirname(experience_file), exist_ok=True)

    existing = ""
    if os.path.exists(experience_file):
        with open(experience_file, "r", encoding="utf-8") as f:
            existing = f.read()

    intent = plan.get("intent", "")
    steps_desc = ", ".join(s.get("agent", "") for s in plan.get("steps", []))
    results_desc = "; ".join(
        f"step {r.get('step_id')}: {r.get('status')}" for r in step_results
    )

    entry = (
        f"\n## 经验\n"
        f"- **意图**: {intent}\n"
        f"- **规划**: [{steps_desc}]\n"
        f"- **结果**: {results_desc}\n"
        f"- **反思**: {reflection_feedback or '无'}\n"
    )

    header = "# 任务规划反思经验\n" if not existing else ""
    with open(experience_file, "a", encoding="utf-8") as f:
        f.write(header + entry)

    return {}


# === Route Functions ===

def route_from_confirm(state: SupervisorState) -> Literal["dispatch", "planner", "end"]:
    """Route after confirm_plan: confirmed→dispatch, rejected→planner, over limit→end"""
    plan = state.get("plan") or {}
    if plan.get("confirmed", False):
        return "dispatch"
    if state.get("confirm_retry_count", 0) >= state.get("max_confirm_retries", 3):
        return "end"
    return "planner"


def route_from_dispatch(state: SupervisorState) -> Literal["code_analyzer", "case_reviewer", "reflect"]:
    """Route after dispatch: more steps→worker, all done→reflect"""
    plan = state.get("plan") or {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    current_index = state.get("current_step_index", 0)

    if current_index >= len(steps):
        return "reflect"

    agent = steps[current_index].get("agent", "")
    if agent == "code_analyzer":
        return "code_analyzer"
    elif agent == "case_reviewer":
        return "case_reviewer"
    return "reflect"


def route_from_reflect(state: SupervisorState) -> Literal["planner", "synthesize"]:
    """Route after reflect: replan→planner, complete→synthesize"""
    if state.get("needs_replan") and state.get("plan_iterations", 0) < state.get("max_plan_iterations", 1):
        return "planner"
    return "synthesize"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_supervisor.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add test_agents/agents/supervisor.py test_agents/tests/test_supervisor.py
git commit -m "feat: rewrite supervisor with Plan-and-Solve + Reflection nodes and route functions"
```

---

### Task 8: Graph Builder

**Files:**
- Rewrite: `test_agents/graph/builder.py`
- Rewrite: `test_agents/tests/test_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
# test_agents/tests/test_builder.py
from unittest.mock import MagicMock, patch

from test_agents.graph.builder import build_graph


def test_build_graph_returns_compiled_graph():
    with patch("test_agents.graph.builder.get_llm") as mock_get_llm, \
         patch("test_agents.graph.builder.build_code_analyzer_graph") as mock_ca, \
         patch("test_agents.graph.builder.build_case_reviewer_graph") as mock_cr:
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        mock_get_llm.return_value = mock_llm
        mock_ca.return_value = MagicMock()
        mock_cr.return_value = MagicMock()
        graph = build_graph()
        assert graph is not None


def test_graph_has_all_nodes():
    with patch("test_agents.graph.builder.get_llm") as mock_get_llm, \
         patch("test_agents.graph.builder.build_code_analyzer_graph") as mock_ca, \
         patch("test_agents.graph.builder.build_case_reviewer_graph") as mock_cr:
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        mock_ca.return_value = MagicMock()
        mock_cr.return_value = MagicMock()
        graph = build_graph()
        node_names = set(graph.get_graph().nodes.keys())
        for expected in ["planner", "confirm_plan", "dispatch", "code_analyzer", "case_reviewer", "reflect", "synthesize", "save_experience"]:
            assert expected in node_names, f"Missing node: {expected}"


def test_graph_starts_at_planner():
    with patch("test_agents.graph.builder.get_llm") as mock_get_llm, \
         patch("test_agents.graph.builder.build_code_analyzer_graph") as mock_ca, \
         patch("test_agents.graph.builder.build_case_reviewer_graph") as mock_cr:
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        mock_ca.return_value = MagicMock()
        mock_cr.return_value = MagicMock()
        graph = build_graph()
        g = graph.get_graph()
        # First node after __start__ should be planner
        edges_from_start = [e for e in g.edges if e[0] == "__start__"]
        assert any("planner" in str(e) for e in edges_from_start)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_builder.py -v`
Expected: FAIL — import/attribute errors from new builder

- [ ] **Step 3: Write the implementation**

```python
# test_agents/graph/builder.py
"""Graph builder - main graph assembly for Plan-and-Solve + Reflection"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

from test_agents.agents.supervisor import (
    planner_node,
    confirm_plan_node,
    dispatch_node,
    reflect_node,
    synthesize_node,
    save_experience_node,
    route_from_confirm,
    route_from_dispatch,
    route_from_reflect,
    get_llm,
)
from test_agents.agents.code_analyzer import (
    build_code_analyzer_graph,
    code_analyzer_wrapper,
)
from test_agents.agents.case_reviewer import (
    build_case_reviewer_graph,
    case_reviewer_wrapper,
)
from test_agents.graph.state import SupervisorState


def build_graph():
    """Build and compile the supervisor graph with worker subgraphs"""
    llm = get_llm()

    code_analyzer_tools = _get_code_analyzer_tools()
    case_reviewer_tools = _get_case_reviewer_tools()

    llm_with_ca_tools = llm.bind_tools(code_analyzer_tools)
    llm_with_cr_tools = llm.bind_tools(case_reviewer_tools)

    build_code_analyzer_graph(llm, llm_with_ca_tools)
    build_case_reviewer_graph(llm, llm_with_cr_tools)

    graph = StateGraph(SupervisorState)

    # Add nodes
    graph.add_node("planner", planner_node)
    graph.add_node("confirm_plan", confirm_plan_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("code_analyzer", code_analyzer_wrapper)
    graph.add_node("case_reviewer", case_reviewer_wrapper)
    graph.add_node("reflect", reflect_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("save_experience", save_experience_node)

    # Fixed edges
    graph.add_edge(START, "planner")
    graph.add_edge("code_analyzer", "dispatch")
    graph.add_edge("case_reviewer", "dispatch")
    graph.add_edge("synthesize", "save_experience")
    graph.add_edge("save_experience", END)

    # Conditional edges
    graph.add_conditional_edges("planner", lambda state: "confirm_plan", {"confirm_plan": "confirm_plan"})

    graph.add_conditional_edges(
        "confirm_plan",
        route_from_confirm,
        {"dispatch": "dispatch", "planner": "planner", "end": END},
    )

    graph.add_conditional_edges(
        "dispatch",
        route_from_dispatch,
        {"code_analyzer": "code_analyzer", "case_reviewer": "case_reviewer", "reflect": "reflect"},
    )

    graph.add_conditional_edges(
        "reflect",
        route_from_reflect,
        {"planner": "planner", "synthesize": "synthesize"},
    )

    memory = InMemorySaver()
    return graph.compile(checkpointer=memory)


def _get_code_analyzer_tools():
    from test_agents.tools.langchain_adapters import claude_cli
    return [claude_cli]


def _get_case_reviewer_tools():
    from test_agents.tools.langchain_adapters import claude_cli, parse_test_cases, query_business_knowledge
    return [claude_cli, parse_test_cases, query_business_knowledge]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_builder.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add test_agents/graph/builder.py test_agents/tests/test_builder.py
git commit -m "feat: rewrite graph builder with Plan-and-Solve + Reflection orchestration"
```

---

### Task 9: Main Entry Point

**Files:**
- Rewrite: `test_agents/main.py`
- Rewrite: `test_agents/tests/test_main.py`

- [ ] **Step 1: Write the failing tests**

```python
# test_agents/tests/test_main.py
from unittest.mock import patch, MagicMock

from test_agents.main import is_simple_request, run_test_agents


class TestIsSimpleRequest:
    def test_code_analysis_detected(self):
        assert is_simple_request("分析 payment 模块代码变更") == "code_analyzer"

    def test_code_change_keyword(self):
        assert is_simple_request("查看 code change") == "code_analyzer"

    def test_case_review_detected(self):
        assert is_simple_request("评审测试用例") == "case_reviewer"

    def test_complex_request_returns_none(self):
        assert is_simple_request("分析代码变更并评审测试用例") is None

    def test_unknown_request_returns_none(self):
        assert is_simple_request("帮我写个测试") is None


class TestRunTestAgents:
    def test_supervisor_mode_invoked(self):
        mock_app = MagicMock()
        mock_app.invoke.return_value = {"final_answer": "结果"}
        mock_app.get_state.return_value = MagicMock(next=[])
        with patch("test_agents.main.build_graph", return_value=mock_app):
            result = run_test_agents("分析代码变更并评审测试用例")
        assert "final_answer" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_main.py -v`
Expected: FAIL — old main.py doesn't have `is_simple_request`

- [ ] **Step 3: Write the implementation**

```python
# test_agents/main.py
"""CLI 入口点 - 自然语言输入 + 双模式调度"""

import argparse
import json
import sys

from langgraph.types import Command

from test_agents.config import config
from test_agents.graph.builder import build_graph


_SINGLE_AGENT_KEYWORDS = {
    "code_analyzer": ["分析代码", "代码变更", "code change", "git diff", "代码分析"],
    "case_reviewer": ["评审用例", "测试用例评审", "case review", "用例评审"],
}


def is_simple_request(user_request: str) -> str | None:
    """Check if request maps to a single agent. Returns agent name or None."""
    matches = []
    for agent, keywords in _SINGLE_AGENT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in user_request.lower():
                matches.append(agent)
                break

    if len(matches) == 1:
        return matches[0]
    return None


def _build_initial_state(user_request: str) -> dict:
    """Build initial SupervisorState for graph invocation"""
    return {
        "user_request": user_request,
        "targets": [],
        "test_cases": [],
        "business_knowledge": "",
        "plan": None,
        "current_step_index": 0,
        "step_results": [],
        "needs_replan": False,
        "reflection_feedback": None,
        "max_plan_iterations": config.MAX_PLAN_ITERATIONS,
        "plan_iterations": 0,
        "confirm_retry_count": 0,
        "max_confirm_retries": config.MAX_CONFIRM_RETRIES,
        "code_change_report": "",
        "review_results": [],
        "final_answer": None,
        "messages": [],
    }


def run_test_agents(user_request: str) -> dict:
    """运行测试智能体群"""
    app = build_graph()
    thread_config = {"configurable": {"thread_id": "test-agents-session"}}
    initial_state = _build_initial_state(user_request)

    result = app.invoke(initial_state, thread_config)

    # Handle interrupts (confirm_plan)
    while True:
        state = app.get_state(thread_config)
        if not state.next:
            break
        # Graph is paused at confirm_plan
        plan = state.values.get("plan", {})
        _display_plan(plan)
        confirmed = input("\n确认计划？(y/n): ").lower().strip()
        if confirmed == "y":
            app.invoke(Command(resume={"confirmed": True}), thread_config)
        else:
            feedback = input("请输入修改建议: ")
            app.invoke(Command(resume={"confirmed": False, "feedback": feedback}), thread_config)

    # Get final state
    final_state = app.get_state(thread_config)
    return final_state.values


def _display_plan(plan: dict):
    """Display execution plan for user confirmation"""
    if not plan:
        print("（无计划）")
        return
    print(f"\n执行计划: {plan.get('intent', 'N/A')}")
    print("-" * 40)
    for step in plan.get("steps", []):
        print(f"  步骤 {step.get('step_id')}: [{step.get('agent')}] {step.get('description')}")


def main():
    """CLI 主函数"""
    parser = argparse.ArgumentParser(description="测试智能体群 v3")
    parser.add_argument("request", nargs="?", help="自然语言需求描述")
    parser.add_argument("--output", default="text", choices=["json", "text"], help="输出格式")
    args = parser.parse_args()

    if args.request:
        user_request = args.request
    else:
        user_request = input("请输入需求: ")

    result = run_test_agents(user_request)

    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        if result.get("final_answer"):
            print(f"\n{result['final_answer']}")
        else:
            print("\n（未生成最终结果）")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_main.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add test_agents/main.py test_agents/tests/test_main.py
git commit -m "feat: rewrite main entry point with natural language input and dual mode"
```

---

### Task 10: Integration Tests

**Files:**
- Rewrite: `test_agents/tests/test_integration.py`

- [ ] **Step 1: Write the failing tests**

```python
# test_agents/tests/test_integration.py
"""Integration tests for Test Agents v3 with mocked LLM"""

import json
from unittest.mock import MagicMock, patch

from test_agents.graph.state import ExecutionPlan, SupervisorState


def _make_mock_llm(plan_dict=None, reflect_complete=True, synthesize_answer="综合报告"):
    """Create a mock LLM that handles all supervisor node calls"""
    mock_llm = MagicMock()

    # planner: with_structured_output returns plan
    structured_mock = MagicMock()
    structured_mock.invoke.return_value = plan_dict or ExecutionPlan(
        intent="分析代码变更并评审测试用例",
        steps=[
            {"step_id": 1, "agent": "code_analyzer", "description": "分析代码变更", "input_mapping": {"module_name": "payment", "source_commit": "abc1234", "target_commit": "def5678"}},
            {"step_id": 2, "agent": "case_reviewer", "description": "评审测试用例", "input_mapping": {"code_change_report": "${code_change_report}"}},
        ],
    ).model_dump()
    mock_llm.with_structured_output.return_value = structured_mock

    # reflect: returns COMPLETE or REPLAN
    reflect_result = MagicMock()
    reflect_result.content = '{"assessment": "COMPLETE", "feedback": ""}' if reflect_complete else '{"assessment": "REPLAN", "feedback": "需要重试"}'
    mock_llm.invoke.return_value = reflect_result

    # bind_tools: returns a mock for worker agent nodes
    mock_llm_with_tools = MagicMock()
    agent_response = MagicMock()
    agent_response.content = "分析结果内容"
    agent_response.tool_calls = []
    mock_llm_with_tools.invoke.return_value = agent_response

    return mock_llm, mock_llm_with_tools


def test_full_pipeline_with_mocks():
    """Test complete supervisor pipeline: planner → confirm → dispatch → workers → reflect → synthesize"""
    mock_llm, mock_llm_with_tools = _make_mock_llm()

    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm), \
         patch("test_agents.agents.supervisor.interrupt", return_value={"confirmed": True}), \
         patch("test_agents.graph.builder.get_llm", return_value=mock_llm), \
         patch("test_agents.agents.code_analyzer.code_analyzer_graph") as mock_ca_graph, \
         patch("test_agents.agents.case_reviewer.case_reviewer_graph") as mock_cr_graph, \
         patch("test_agents.agents.code_analyzer.build_code_analyzer_graph", return_value=MagicMock()), \
         patch("test_agents.agents.case_reviewer.build_case_reviewer_graph", return_value=MagicMock()):

        mock_ca_graph.invoke.return_value = {
            "result": "## 变更概述\n新增支付功能",
            "messages": [],
            "error": "no",
        }
        mock_cr_graph.invoke.return_value = {
            "result": '[{"case_id": "TC001", "verdict": "pass"}]',
            "messages": [],
            "error": "no",
        }

        from test_agents.graph.builder import build_graph
        app = build_graph()

        initial_state = _build_initial_state("分析 payment 模块代码变更并评审测试用例")
        result = app.invoke(initial_state, {"configurable": {"thread_id": "test-integration"}})

        assert result.get("final_answer") is not None


def test_route_functions_integration():
    """Test route functions with realistic state"""
    from test_agents.agents.supervisor import route_from_confirm, route_from_dispatch, route_from_reflect

    # After confirm (confirmed=True) → dispatch
    state: SupervisorState = {
        "plan": {"confirmed": True, "intent": "test", "steps": [{"step_id": 1, "agent": "code_analyzer"}]},
    }
    assert route_from_confirm(state) == "dispatch"

    # After first worker → second worker
    state = {
        "plan": {"steps": [{"agent": "code_analyzer"}, {"agent": "case_reviewer"}]},
        "current_step_index": 1,
    }
    assert route_from_dispatch(state) == "case_reviewer"

    # All steps done → reflect
    state = {
        "plan": {"steps": [{"agent": "code_analyzer"}]},
        "current_step_index": 1,
    }
    assert route_from_dispatch(state) == "reflect"

    # Reflect complete → synthesize
    state = {"needs_replan": False, "plan_iterations": 0, "max_plan_iterations": 1}
    assert route_from_reflect(state) == "synthesize"


def test_worker_state_mapping():
    """Test that worker wrapper correctly maps SupervisorState → WorkerState → SupervisorState"""
    from test_agents.agents.code_analyzer import code_analyzer_wrapper, _resolve_input

    # Test _resolve_input with state reference
    state: SupervisorState = {
        "code_change_report": "existing report",
        "test_cases": [{"case_id": "TC001"}],
    }
    assert _resolve_input("${code_change_report}", state) == "existing report"
    assert _resolve_input("payment", state) == "payment"

    # Test _resolve_input with list field
    result = _resolve_input("${test_cases}", state)
    parsed = json.loads(result)
    assert parsed[0]["case_id"] == "TC001"


def _build_initial_state(user_request: str) -> dict:
    return {
        "user_request": user_request,
        "targets": [],
        "test_cases": [],
        "business_knowledge": "",
        "plan": None,
        "current_step_index": 0,
        "step_results": [],
        "needs_replan": False,
        "reflection_feedback": None,
        "max_plan_iterations": 1,
        "plan_iterations": 0,
        "confirm_retry_count": 0,
        "max_confirm_retries": 3,
        "code_change_report": "",
        "review_results": [],
        "final_answer": None,
        "messages": [],
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_integration.py -v`
Expected: FAIL — various import and logic errors from the integration

- [ ] **Step 3: Fix any issues found during integration testing**

Run the tests, identify failures, and fix them. Common issues may include:
- Import path mismatches
- State field naming inconsistencies
- Mock return value shapes not matching expected formats
- Missing `__init__.py` exports

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/test_integration.py -v`
Iterate until all tests pass.

- [ ] **Step 4: Run full test suite**

Run: `cd /mnt/d/testagents && python -m pytest test_agents/tests/ -v`
Expected: PASS (all tests — old test_claude_cli.py and test_tools_misc.py should still pass)

- [ ] **Step 5: Commit**

```bash
git add test_agents/tests/test_integration.py
git commit -m "feat: add integration tests for v3 Plan-and-Solve + Reflection pipeline"
```

---

## Self-Review

### 1. Spec Coverage

| Spec Section | Task |
|---|---|
| 2.1 架构设计 (Plan-and-Solve + Reflection) | Tasks 7, 8 |
| 2.2 目录结构 | All tasks |
| 3.1 SupervisorState | Task 1 |
| 3.2 WorkerState | Task 1 |
| 3.3 主图与子图状态映射 | Task 6 |
| 3.4 多模块聚合规则 | Task 6 (code_analyzer_wrapper) |
| 3.5 input_mapping 规则 | Task 6 (_resolve_input) |
| 4.1 Planner 节点 | Task 7 |
| 4.2 ConfirmPlan 节点 | Task 7 |
| 4.3 Dispatch 节点 | Task 7 |
| 4.4 Reflect 节点 | Task 7 |
| 4.5 SaveExperience 节点 | Task 7 |
| 4.6 Synthesize 节点 | Task 7 |
| 4.7 Worker 子图 | Tasks 5, 6 |
| 5.1-5.2 图编排与路由 | Task 8 |
| 5.3 完整执行流程 | Task 10 |
| 5.4 直接调用模式 | Task 9 |
| 6 工具层设计 | Task 3 |
| 8 错误处理 | Task 7 (within nodes) |
| 10 依赖 | Task 2 (config) |
| 12 反思与经验机制 | Tasks 5, 7 |

### 2. Placeholder Scan

- No "TBD", "TODO", "implement later" found
- No "add appropriate error handling" without code
- No "Write tests for the above" without actual test code
- All code steps have complete implementations

### 3. Type Consistency

- `SupervisorState.plan` is `Optional[dict]` throughout — all nodes read/write as dict
- `WorkerState` fields consistent across worker_base.py, code_analyzer.py, case_reviewer.py
- `StepResult` used via `.model_dump()` in worker wrappers, stored as plain dicts in state
- `_resolve_input` function signature consistent across both worker files
- Route function return types match conditional edge mappings in builder
