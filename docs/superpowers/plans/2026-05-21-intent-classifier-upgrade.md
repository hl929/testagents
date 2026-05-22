# Intent Classifier 升级为意图解析器 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 intent_classifier 从纯分类器升级为"分类 + 结构化提取"，relevant 请求的意图解析结果直接复用给 planner，消除信息断层。

**Architecture:** 在现有 intent_classifier_node 中新增 `extracted` 字段解析逻辑，仅 `relevant` 分类时通过 `IntentExtraction` Pydantic 模型校验后写入 `intent_analysis` state 字段。planner_node 读取 `intent_analysis` 作为辅助参考。降级路径：extracted 解析失败时 `intent_analysis = None`，planner 回退到原始行为。

**Tech Stack:** Python, Pydantic, LangGraph, LangChain, pytest

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `test_agents/graph/state.py` | Modify | 新增 `IntentExtraction` Pydantic 模型；`SupervisorState` 新增 `intent_analysis` 字段 |
| `test_agents/prompts/intent_classifier.md` | Modify | 重写 prompt：relevant 时要求输出 `extracted`，ambiguous/irrelevant 不输出 |
| `test_agents/agents/supervisor.py` | Modify | `intent_classifier_node` 解析 extracted；`planner_node` 读取 intent_analysis；新增 `_format_intent_analysis` |
| `test_agents/prompts/planner.md` | Modify | 新增 `{intent_analysis}` 占位符和使用说明 |
| `test_agents/main.py` | Modify | `_build_initial_state` 新增 `intent_analysis` 初始值 |
| `test_agents/tests/test_supervisor.py` | Modify | 更新 mock 和断言，新增 extracted 降级测试 |
| `test_agents/tests/test_integration.py` | Modify | 更新 mock 返回值，relevant 请求的 classifier mock 包含 extracted |

---

### Task 1: 新增 IntentExtraction 模型 + SupervisorState 字段

**Files:**
- Modify: `test_agents/graph/state.py:3-8` (imports), `test_agents/graph/state.py:58-78` (SupervisorState)

- [ ] **Step 1: 写失败测试**

在 `test_agents/tests/test_supervisor.py` 顶部新增导入和测试：

```python
from test_agents.graph.state import SupervisorState, ExecutionPlan, IntentExtraction


def test_intent_extraction_model_validates():
    """IntentExtraction accepts valid extracted data"""
    extracted = IntentExtraction(
        goal="分析代码变更并评审测试用例",
        modules=["payment"],
        source_commit="abc1234",
        target_commit="def5678",
        needs_code_analysis=True,
        needs_case_review=True,
    )
    assert extracted.goal == "分析代码变更并评审测试用例"
    assert extracted.modules == ["payment"]
    assert extracted.needs_code_analysis is True


def test_intent_extraction_model_defaults():
    """IntentExtraction fields have sensible defaults"""
    extracted = IntentExtraction(goal="评审测试用例")
    assert extracted.modules == []
    assert extracted.source_commit == ""
    assert extracted.target_commit == ""
    assert extracted.needs_code_analysis is False
    assert extracted.needs_case_review is False
    assert extracted.test_cases_provided is False
    assert extracted.missing_info == []


def test_supervisor_state_has_intent_analysis():
    state: SupervisorState = {
        "intent_classification": "relevant",
        "intent_reason": "明确需求",
        "intent_analysis": {"goal": "分析代码变更"},
    }
    assert state["intent_analysis"] == {"goal": "分析代码变更"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test_agents/tests/test_supervisor.py::test_intent_extraction_model_validates test_agents/tests/test_supervisor.py::test_intent_extraction_model_defaults test_agents/tests/test_supervisor.py::test_supervisor_state_has_intent_analysis -v`
Expected: FAIL — `ImportError: cannot import name 'IntentExtraction'`

- [ ] **Step 3: 实现 IntentExtraction 模型和 state 字段**

在 `test_agents/graph/state.py` 中，在 `AnalysisTarget` 类之后新增 `IntentExtraction`：

```python
class IntentExtraction(BaseModel):
    goal: str = Field(description="用户核心意图，如'分析代码变更并评审测试用例'")
    modules: list[str] = Field(default_factory=list, description="涉及的模块名列表")
    source_commit: str = Field(default="", description="源 commit SHA")
    target_commit: str = Field(default="", description="目标 commit SHA")
    needs_code_analysis: bool = Field(default=False, description="是否需要代码变更分析")
    needs_case_review: bool = Field(default=False, description="是否需要测试用例评审")
    test_cases_provided: bool = Field(default=False, description="用户是否提供了测试用例")
    missing_info: list[str] = Field(default_factory=list, description="缺少的关键信息")
```

在 `SupervisorState` 中，在 `intent_reason: str` 行之后新增：

```python
    intent_analysis: Optional[dict]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test_agents/tests/test_supervisor.py::test_intent_extraction_model_validates test_agents/tests/test_supervisor.py::test_intent_extraction_model_defaults test_agents/tests/test_supervisor.py::test_supervisor_state_has_intent_analysis -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/graph/state.py test_agents/tests/test_supervisor.py
git commit -m "feat(state): add IntentExtraction model and intent_analysis field to SupervisorState"
```

---

### Task 2: 重写 intent_classifier.md prompt

**Files:**
- Modify: `test_agents/prompts/intent_classifier.md`

- [ ] **Step 1: 写失败测试**

在 `test_agents/tests/test_supervisor.py` 的 `TestIntentClassifierNode` 类中新增测试，验证 prompt 包含 `extracted` 相关指令：

```python
def test_classifier_prompt_mentions_extracted(self):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='{"classification": "relevant", "reason": "test", "extracted": {"goal": "分析代码"}}'
    )
    state: SupervisorState = {"user_request": "分析代码", "messages": []}
    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
        intent_classifier_node(state)
    prompt_arg = mock_llm.invoke.call_args[0][0][0].content
    assert "extracted" in prompt_arg
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test_agents/tests/test_supervisor.py::TestIntentClassifierNode::test_classifier_prompt_mentions_extracted -v`
Expected: FAIL — `"extracted" not in prompt_arg`

- [ ] **Step 3: 重写 intent_classifier.md**

将 `test_agents/prompts/intent_classifier.md` 整体替换为：

```markdown
你是 Test Agents 系统的意图分类器。你的任务是判断用户的需求是否属于本系统的能力范围，并对相关请求提取结构化意图信息。

## 本系统能力

- 分析代码变更（git diff）
- 评审测试用例

## 分类规则

- `relevant`：明确提到代码分析、代码变更、git diff、测试用例评审
- `ambiguous`：提到"测试""看看代码""帮我看看"等关键词，但不明确具体需求（缺少模块名、commit 范围或具体操作）
- `irrelevant`：打招呼、闲聊、天气、数学计算、与代码/测试完全无关的内容

## 输出格式

### relevant 请求

输出 JSON 对象，包含以下字段：
- `classification`: `"relevant"`
- `reason`: 分类理由，一句话说明为什么这样分类
- `extracted`: 结构化意图信息，包含以下字段：
  - `goal`: 用户核心意图（如"分析代码变更并评审测试用例"）
  - `modules`: 涉及的模块名列表（如 `["payment"]`）
  - `source_commit`: 源 commit SHA（未提供则为空字符串）
  - `target_commit`: 目标 commit SHA（未提供则为空字符串）
  - `needs_code_analysis`: 是否需要代码变更分析（true/false）
  - `needs_case_review`: 是否需要测试用例评审（true/false）
  - `test_cases_provided`: 用户是否提供了测试用例（true/false）
  - `missing_info`: 缺少的关键信息列表（如 `[]`）

### ambiguous / irrelevant 请求

输出 JSON 对象，包含以下字段：
- `classification`: `"ambiguous"` 或 `"irrelevant"`
- `reason`: 分类理由

**注意：ambiguous / irrelevant 请求不输出 `extracted` 字段。**

## 示例

### 示例 1：relevant
用户需求："分析 payment 模块从 abc1234 到 def5678 的代码变更"
```json
{
  "classification": "relevant",
  "reason": "明确提到代码分析，包含模块名和 commit 范围",
  "extracted": {
    "goal": "分析 payment 模块代码变更",
    "modules": ["payment"],
    "source_commit": "abc1234",
    "target_commit": "def5678",
    "needs_code_analysis": true,
    "needs_case_review": false,
    "test_cases_provided": false,
    "missing_info": []
  }
}
```

### 示例 2：relevant（缺少 commit 范围）
用户需求："分析 payment 模块的代码变更并评审测试用例"
```json
{
  "classification": "relevant",
  "reason": "明确提到代码分析和测试用例评审，包含模块名",
  "extracted": {
    "goal": "分析代码变更并评审测试用例",
    "modules": ["payment"],
    "source_commit": "",
    "target_commit": "",
    "needs_code_analysis": true,
    "needs_case_review": true,
    "test_cases_provided": false,
    "missing_info": ["commit 范围"]
  }
}
```

### 示例 3：ambiguous
用户需求："帮我看看测试"
```json
{"classification": "ambiguous", "reason": "提到测试但未说明具体模块、commit 范围或操作类型"}
```

### 示例 4：irrelevant
用户需求："hello"
```json
{"classification": "irrelevant", "reason": "用户仅打招呼，未提出任何与代码分析或测试评审相关的需求"}
```

## 用户需求

{user_request}

## 执行指令

请根据以上规则和示例，输出 JSON 格式的分类结果。确保输出是合法的 JSON，不要包含任何 markdown 代码块标记之外的内容。
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test_agents/tests/test_supervisor.py::TestIntentClassifierNode::test_classifier_prompt_mentions_extracted -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/prompts/intent_classifier.md test_agents/tests/test_supervisor.py
git commit -m "feat(prompt): upgrade intent_classifier prompt with extracted field for relevant requests"
```

---

### Task 3: 修改 intent_classifier_node 解析 extracted

**Files:**
- Modify: `test_agents/agents/supervisor.py:1-4` (imports), `test_agents/agents/supervisor.py:36-57` (intent_classifier_node)

- [ ] **Step 1: 写失败测试**

在 `test_agents/tests/test_supervisor.py` 的 `TestIntentClassifierNode` 类中新增/修改测试：

```python
def test_classifies_relevant_with_extracted(self):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='{"classification": "relevant", "reason": "明确需求", "extracted": {"goal": "分析代码变更", "modules": ["payment"], "source_commit": "abc1234", "target_commit": "def5678", "needs_code_analysis": true, "needs_case_review": false, "test_cases_provided": false, "missing_info": []}}'
    )
    state: SupervisorState = {"user_request": "分析 payment 模块代码变更", "messages": []}
    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
        result = intent_classifier_node(state)
    assert result["intent_classification"] == "relevant"
    assert result["intent_reason"] == "明确需求"
    assert result["intent_analysis"] is not None
    assert result["intent_analysis"]["goal"] == "分析代码变更"
    assert result["intent_analysis"]["modules"] == ["payment"]

def test_classifies_relevant_without_extracted(self):
    """relevant but extracted missing → intent_analysis = None, classification preserved"""
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='{"classification": "relevant", "reason": "明确需求"}'
    )
    state: SupervisorState = {"user_request": "分析代码变更", "messages": []}
    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
        result = intent_classifier_node(state)
    assert result["intent_classification"] == "relevant"
    assert result["intent_analysis"] is None

def test_classifies_relevant_with_invalid_extracted(self):
    """relevant but extracted has invalid fields → intent_analysis = None, classification preserved"""
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='{"classification": "relevant", "reason": "明确需求", "extracted": {"goal": 123}}'
    )
    state: SupervisorState = {"user_request": "分析代码变更", "messages": []}
    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
        result = intent_classifier_node(state)
    assert result["intent_classification"] == "relevant"
    assert result["intent_analysis"] is None

def test_classifies_ambiguous_no_extracted(self):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='{"classification": "ambiguous", "reason": "信息不足"}'
    )
    state: SupervisorState = {"user_request": "帮我看看测试", "messages": []}
    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
        result = intent_classifier_node(state)
    assert result["intent_classification"] == "ambiguous"
    assert result["intent_analysis"] is None

def test_classifies_irrelevant_no_extracted(self):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='{"classification": "irrelevant", "reason": "打招呼"}'
    )
    state: SupervisorState = {"user_request": "hello", "messages": []}
    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
        result = intent_classifier_node(state)
    assert result["intent_classification"] == "irrelevant"
    assert result["intent_analysis"] is None
```

同时更新旧的 `test_classifies_relevant` 和 `test_classifies_relevant_with_markdown_fenced_json` 测试，使其 mock 返回值包含 `extracted` 并断言 `intent_analysis`：

```python
def test_classifies_relevant(self):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='{"classification": "relevant", "reason": "明确需求", "extracted": {"goal": "分析代码变更"}}'
    )
    state: SupervisorState = {"user_request": "分析 payment 模块代码变更", "messages": []}
    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
        result = intent_classifier_node(state)
    assert result["intent_classification"] == "relevant"
    assert result["intent_reason"] == "明确需求"
    assert result["intent_analysis"] is not None
    assert result["intent_analysis"]["goal"] == "分析代码变更"

def test_classifies_relevant_with_markdown_fenced_json(self):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='```json\n{"classification": "relevant", "reason": "明确需求", "extracted": {"goal": "分析代码变更"}}\n```'
    )
    state: SupervisorState = {"user_request": "分析代码", "messages": []}
    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
        result = intent_classifier_node(state)
    assert result["intent_classification"] == "relevant"
    assert result["intent_analysis"] is not None
```

同时更新 `test_classifies_irrelevant` 断言新增的 `intent_analysis` 为 None：

```python
def test_classifies_irrelevant(self):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content='{"classification": "irrelevant", "reason": "打招呼"}')
    state: SupervisorState = {"user_request": "hello", "messages": []}
    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
        result = intent_classifier_node(state)
    assert result["intent_classification"] == "irrelevant"
    assert result["intent_reason"] == "打招呼"
    assert result["intent_analysis"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test_agents/tests/test_supervisor.py::TestIntentClassifierNode -v`
Expected: FAIL — tests expect `intent_analysis` in result but current code doesn't return it

- [ ] **Step 3: 修改 intent_classifier_node**

在 `test_agents/agents/supervisor.py` 顶部新增导入：

```python
from test_agents.graph.state import SupervisorState, ExecutionPlan, IntentExtraction
```

替换 `intent_classifier_node` 函数：

```python
def intent_classifier_node(state: SupervisorState) -> dict:
    """Classify user request intent and extract structured info for relevant requests."""
    llm = get_llm()
    user_request = state.get("user_request", "")
    prompt = load_prompt("intent_classifier", user_request=user_request)

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = _strip_markdown_json(response.content)
        assessment = json.loads(content)
        classification = assessment.get("classification", "ambiguous")
        reason = assessment.get("reason", "")
        if classification not in ("relevant", "ambiguous", "irrelevant"):
            classification = "ambiguous"

        intent_analysis = None
        if classification == "relevant":
            extracted = assessment.get("extracted")
            if extracted and isinstance(extracted, dict):
                try:
                    validated = IntentExtraction.model_validate(extracted)
                    intent_analysis = validated.model_dump()
                except Exception:
                    intent_analysis = None
    except (json.JSONDecodeError, Exception):
        classification = "ambiguous"
        reason = "意图分类解析失败，默认按模糊请求处理"
        intent_analysis = None

    return {
        "intent_classification": classification,
        "intent_reason": reason,
        "intent_analysis": intent_analysis,
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test_agents/tests/test_supervisor.py::TestIntentClassifierNode -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/agents/supervisor.py test_agents/tests/test_supervisor.py
git commit -m "feat(supervisor): parse extracted field in intent_classifier_node for relevant requests"
```

---

### Task 4: 修改 planner_node 读取 intent_analysis + 新增 _format_intent_analysis

**Files:**
- Modify: `test_agents/agents/supervisor.py:93-116` (planner_node)

- [ ] **Step 1: 写失败测试**

在 `test_agents/tests/test_supervisor.py` 的 `TestPlannerNode` 类中新增测试：

```python
def test_planner_with_intent_analysis(self):
    mock_llm = MagicMock()
    plan_json = ExecutionPlan(
        intent="分析代码变更",
        steps=[{"step_id": 1, "agent": "code_analyzer", "description": "分析代码", "input_mapping": {}}],
    ).model_dump_json()
    mock_llm.invoke.return_value = MagicMock(content=plan_json)

    state: SupervisorState = {
        "user_request": "分析 payment 模块代码变更",
        "intent_analysis": {
            "goal": "分析代码变更",
            "modules": ["payment"],
            "source_commit": "abc1234",
            "target_commit": "def5678",
            "needs_code_analysis": True,
            "needs_case_review": False,
            "test_cases_provided": False,
            "missing_info": [],
        },
        "messages": [],
    }
    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
        result = planner_node(state)
    assert "plan" in result
    prompt_arg = mock_llm.invoke.call_args[0][0][0].content
    assert "核心意图" in prompt_arg
    assert "payment" in prompt_arg

def test_planner_without_intent_analysis(self):
    mock_llm = MagicMock()
    plan_json = ExecutionPlan(
        intent="分析代码变更",
        steps=[{"step_id": 1, "agent": "code_analyzer", "description": "分析代码", "input_mapping": {}}],
    ).model_dump_json()
    mock_llm.invoke.return_value = MagicMock(content=plan_json)

    state: SupervisorState = {
        "user_request": "分析 payment 模块代码变更",
        "intent_analysis": None,
        "messages": [],
    }
    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
        result = planner_node(state)
    assert "plan" in result
    prompt_arg = mock_llm.invoke.call_args[0][0][0].content
    assert "(无)" in prompt_arg
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test_agents/tests/test_supervisor.py::TestPlannerNode::test_planner_with_intent_analysis test_agents/tests/test_supervisor.py::TestPlannerNode::test_planner_without_intent_analysis -v`
Expected: FAIL — `load_prompt()` gets unexpected keyword argument `intent_analysis`, or prompt doesn't contain the analysis text

- [ ] **Step 3: 实现 _format_intent_analysis 和修改 planner_node**

在 `test_agents/agents/supervisor.py` 中，在 `intent_classifier_node` 函数之后新增：

```python
def _format_intent_analysis(analysis: dict) -> str:
    """将 intent_analysis 格式化为 planner 可读的文本"""
    parts = []
    if analysis.get("goal"):
        parts.append(f"- 核心意图：{analysis['goal']}")
    if analysis.get("modules"):
        parts.append(f"- 涉及模块：{', '.join(analysis['modules'])}")
    if analysis.get("source_commit") or analysis.get("target_commit"):
        parts.append(f"- Commit 范围：{analysis.get('source_commit', '?')} → {analysis.get('target_commit', '?')}")
    if analysis.get("needs_code_analysis"):
        parts.append("- 需要：代码变更分析")
    if analysis.get("needs_case_review"):
        parts.append("- 需要：测试用例评审")
    if analysis.get("test_cases_provided"):
        parts.append("- 用户已提供测试用例")
    if analysis.get("missing_info"):
        parts.append(f"- 缺少信息：{', '.join(analysis['missing_info'])}")
    return "\n".join(parts)
```

替换 `planner_node` 函数：

```python
def planner_node(state: SupervisorState) -> dict:
    """Parse user_request and generate ExecutionPlan"""
    llm = get_llm()
    user_request = state.get("user_request", "")
    intent_analysis = state.get("intent_analysis")
    tools_info = ToolRegistry.render_all()

    if intent_analysis:
        analysis_text = _format_intent_analysis(intent_analysis)
    else:
        analysis_text = "(无)"

    prompt = load_prompt(
        "planner",
        user_request=user_request,
        tools_info=tools_info,
        intent_analysis=analysis_text,
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    content = _strip_markdown_json(response.content)

    try:
        plan = ExecutionPlan.model_validate_json(content)
        plan_dict = plan.model_dump()
    except Exception:
        try:
            plan = ExecutionPlan.model_validate(json.loads(content))
            plan_dict = plan.model_dump()
        except Exception:
            plan_dict = {"intent": "解析失败", "steps": [], "confirmed": False}

    return {
        "plan": plan_dict,
        "plan_iterations": state.get("plan_iterations", 0) + 1,
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test_agents/tests/test_supervisor.py::TestPlannerNode -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/agents/supervisor.py
git commit -m "feat(supervisor): planner reads intent_analysis as auxiliary input"
```

---

### Task 5: 修改 planner.md prompt 新增 intent_analysis 占位符

**Files:**
- Modify: `test_agents/prompts/planner.md`

- [ ] **Step 1: 写失败测试**

在 `test_agents/tests/test_supervisor.py` 的 `TestPlannerNode` 类中新增测试：

```python
def test_planner_prompt_contains_intent_analysis_section(self):
    mock_llm = MagicMock()
    plan_json = ExecutionPlan(
        intent="分析代码变更",
        steps=[{"step_id": 1, "agent": "code_analyzer", "description": "分析代码", "input_mapping": {}}],
    ).model_dump_json()
    mock_llm.invoke.return_value = MagicMock(content=plan_json)

    state: SupervisorState = {
        "user_request": "分析代码变更",
        "intent_analysis": {"goal": "分析代码变更"},
        "messages": [],
    }
    with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
        planner_node(state)
    prompt_arg = mock_llm.invoke.call_args[0][0][0].content
    assert "意图解析结果" in prompt_arg
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test_agents/tests/test_supervisor.py::TestPlannerNode::test_planner_prompt_contains_intent_analysis_section -v`
Expected: FAIL — `"意图解析结果" not in prompt_arg`

- [ ] **Step 3: 修改 planner.md**

在 `test_agents/prompts/planner.md` 的 `## 输入` 章节（包含 `{user_request}` 的部分）之后，新增：

```markdown

## 意图解析结果

{intent_analysis}

如果意图解析结果可用（非"(无)"），直接基于其中的核心意图、涉及模块、Commit 范围生成步骤，无需重新理解用户需求。如果意图解析结果为"(无)"，根据用户需求原文自行理解。
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test_agents/tests/test_supervisor.py::TestPlannerNode::test_planner_prompt_contains_intent_analysis_section -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/prompts/planner.md test_agents/tests/test_supervisor.py
git commit -m "feat(prompt): add intent_analysis placeholder to planner prompt"
```

---

### Task 6: 更新 main.py 初始状态

**Files:**
- Modify: `test_agents/main.py:36-56` (_build_initial_state)

- [ ] **Step 1: 写失败测试**

在 `test_agents/tests/test_supervisor.py` 中新增（测试 main 模块的初始状态构建）：

```python
from test_agents.main import _build_initial_state


def test_build_initial_state_includes_intent_analysis():
    state = _build_initial_state("测试请求")
    assert "intent_analysis" in state
    assert state["intent_analysis"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test_agents/tests/test_supervisor.py::test_build_initial_state_includes_intent_analysis -v`
Expected: FAIL — `assert None is None` fails because key missing, or `KeyError`

- [ ] **Step 3: 修改 _build_initial_state**

在 `test_agents/main.py` 的 `_build_initial_state` 函数中，在 `"intent_reason": "",` 行之后新增：

```python
        "intent_analysis": None,
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test_agents/tests/test_supervisor.py::test_build_initial_state_includes_intent_analysis -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/main.py test_agents/tests/test_supervisor.py
git commit -m "feat(main): add intent_analysis=None to initial state"
```

---

### Task 7: 更新集成测试 mock 返回值

**Files:**
- Modify: `test_agents/tests/test_integration.py:168-247` (test_full_pipeline_mocked), `test_agents/tests/test_integration.py:297-346` (test_relevant_request_goes_full_pipeline)

- [ ] **Step 1: 写失败测试 — 先运行现有集成测试确认基线**

Run: `python -m pytest test_agents/tests/test_integration.py -v`
Expected: Some tests may fail because intent_classifier_node now expects `extracted` in relevant LLM responses, or because `_build_initial_state` is missing `intent_analysis`. Check which tests fail.

- [ ] **Step 2: 更新 test_full_pipeline_mocked**

将 `test_integration.py` 中 `mock_classifier_response` 的 content 更新为包含 `extracted`：

```python
mock_classifier_response = MagicMock()
mock_classifier_response.content = json.dumps({
    "classification": "relevant",
    "reason": "明确需求",
    "extracted": {
        "goal": "测试订单模块",
        "modules": ["订单"],
        "source_commit": "",
        "target_commit": "",
        "needs_code_analysis": True,
        "needs_case_review": True,
        "test_cases_provided": False,
        "missing_info": ["commit 范围"],
    },
}, ensure_ascii=False)
```

- [ ] **Step 3: 更新 test_relevant_request_goes_full_pipeline**

同样更新该测试中的 `mock_classifier_response`：

```python
mock_classifier_response = MagicMock()
mock_classifier_response.content = json.dumps({
    "classification": "relevant",
    "reason": "明确需求",
    "extracted": {
        "goal": "分析订单模块代码变更",
        "modules": ["订单"],
        "source_commit": "",
        "target_commit": "",
        "needs_code_analysis": True,
        "needs_case_review": False,
        "test_cases_provided": False,
        "missing_info": ["commit 范围"],
    },
}, ensure_ascii=False)
```

- [ ] **Step 4: 运行全部集成测试确认通过**

Run: `python -m pytest test_agents/tests/test_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/tests/test_integration.py
git commit -m "test(integration): update mock classifier responses with extracted field"
```

---

### Task 8: 全量回归测试

**Files:** 无新增修改

- [ ] **Step 1: 运行全部测试**

Run: `python -m pytest test_agents/tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: 如有失败，修复并重新运行**

常见问题：
- 某些测试 mock 了旧格式（不含 `extracted`）的 classifier 响应 → 添加 `"extracted": null` 或完整的 extracted 对象
- `test_fallback_to_ambiguous_on_invalid_json` / `test_fallback_to_ambiguous_on_llm_exception` → 确认这两个测试的 result 包含 `intent_analysis` 为 None

- [ ] **Step 3: 全部通过后 commit（如有修复）**

```bash
git add -u
git commit -m "fix: resolve test regressions from intent_analysis integration"
```

---

## Self-Review

**1. Spec coverage:**
- IntentExtraction 模型 → Task 1
- SupervisorState.intent_analysis → Task 1
- intent_classifier prompt 重写 → Task 2
- intent_classifier_node 解析 extracted → Task 3
- planner_node 读取 intent_analysis → Task 4
- _format_intent_analysis → Task 4
- planner.md intent_analysis 占位符 → Task 5
- main.py 初始状态 → Task 6
- 集成测试更新 → Task 7
- 降级场景（relevant without extracted, invalid extracted） → Task 3 tests
- 回归测试 → Task 8

**2. Placeholder scan:** No TBD/TODO found. All code blocks contain actual implementation.

**3. Type consistency:**
- `IntentExtraction` defined in state.py (Task 1), imported in supervisor.py (Task 3)
- `intent_analysis` is `Optional[dict]` in state, accessed via `state.get("intent_analysis")` returning `None` or `dict`
- `_format_intent_analysis(analysis: dict)` matches `intent_analysis` dict type
- All test mocks use consistent JSON structure matching `IntentExtraction` fields
