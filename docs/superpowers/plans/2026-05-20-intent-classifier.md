# Intent Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `intent_classifier_node` and `reply_node` to the Supervisor graph so irrelevant or ambiguous user requests get a friendly response before entering the planner, eliminating the current awkward flow where empty plans are confirmed then synthesize into failure messages.

**Architecture:** Insert an LLM-based intent classification step at the graph entry point. Three-way classification (`relevant` / `ambiguous` / `irrelevant`) routes either to `planner` or directly to `reply` → `END`. The reply node uses a dedicated prompt to generate natural, helpful responses.

**Tech Stack:** Python, LangGraph, LangChain OpenAI, Pydantic, pytest

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `test_agents/graph/state.py` | Modify | Add `intent_classification` and `intent_reason` to `SupervisorState` |
| `test_agents/agents/supervisor.py` | Modify | Add `intent_classifier_node`, `reply_node`, `route_from_classifier` |
| `test_agents/prompts/intent_classifier.md` | Create | Prompt template for LLM intent classification |
| `test_agents/prompts/reply.md` | Create | Prompt template for generating friendly replies to irrelevant/ambiguous requests |
| `test_agents/graph/builder.py` | Modify | Wire new nodes into graph: `START → intent_classifier → (route) → planner/reply` |
| `test_agents/main.py` | Modify | Add new state fields to `_build_initial_state()` |
| `test_agents/tests/test_supervisor.py` | Modify | Add unit tests for classifier node, reply node, and new route |
| `test_agents/tests/test_integration.py` | Modify | Add end-to-end tests for irrelevant and ambiguous request flows |

---

### Task 1: Add intent classification fields to SupervisorState

**Files:**
- Modify: `test_agents/graph/state.py:58-74`

- [ ] **Step 1: Write the failing test**

Add to `test_agents/tests/test_supervisor.py` (or create a new test file):

```python
def test_supervisor_state_has_intent_fields():
    from test_agents.graph.state import SupervisorState
    # TypedDict allows optional fields, so we verify by construction
    state: SupervisorState = {
        "user_request": "hello",
        "intent_classification": "irrelevant",
        "intent_reason": "用户仅打招呼",
    }
    assert state["intent_classification"] == "irrelevant"
    assert state["intent_reason"] == "用户仅打招呼"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_agents/tests/test_supervisor.py::test_supervisor_state_has_intent_fields -v`

Expected: PASS (TypedDict allows any key at runtime, so this passes even before modification. The real validation is that downstream code uses these keys.)

- [ ] **Step 3: Add fields to SupervisorState**

In `test_agents/graph/state.py`, after `messages` field, add:

```python
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
    outputs: Annotated[dict, operator.or_]
    final_answer: Optional[str]
    messages: Annotated[list[AnyMessage], add_messages]
    intent_classification: str
    intent_reason: str
```

- [ ] **Step 4: Commit**

```bash
git add test_agents/graph/state.py
git commit -m "feat(state): add intent_classification and intent_reason to SupervisorState"
```

---

### Task 2: Create intent_classifier.md prompt template

**Files:**
- Create: `test_agents/prompts/intent_classifier.md`

- [ ] **Step 1: Create prompt file**

```markdown
你是 Test Agents 系统的意图分类器。你的任务是判断用户的需求是否属于本系统的能力范围。

## 本系统能力

- 分析代码变更（git diff）
- 评审测试用例

## 分类规则

- `relevant`：明确提到代码分析、代码变更、git diff、测试用例评审、模块名 + commit 范围等
- `ambiguous`：提到"测试""看看代码""帮我看看"等关键词，但不明确具体需求（缺少模块名、commit 范围或具体操作）
- `irrelevant`：打招呼、闲聊、天气、数学计算、与代码/测试完全无关的内容

## 输出格式

输出 JSON 对象，包含以下字段：
- `classification`: `"relevant"` | `"ambiguous"` | `"irrelevant"`
- `reason`: 分类理由，一句话说明为什么这样分类

## 示例

### 示例 1：relevant
用户需求："分析 payment 模块从 abc1234 到 def5678 的代码变更"
```json
{"classification": "relevant", "reason": "明确提到代码分析，包含模块名和 commit 范围"}
```

### 示例 2：ambiguous
用户需求："帮我看看测试"
```json
{"classification": "ambiguous", "reason": "提到测试但未说明具体模块、commit 范围或操作类型"}
```

### 示例 3：irrelevant
用户需求："hello"
```json
{"classification": "irrelevant", "reason": "用户仅打招呼，未提出任何与代码分析或测试评审相关的需求"}
```

## 用户需求

{user_request}

## 执行指令

请根据以上规则和示例，输出 JSON 格式的分类结果。确保输出是合法的 JSON，不要包含任何 markdown 代码块标记之外的内容。
```

- [ ] **Step 2: Verify prompt loads correctly**

Run a quick smoke test:
```python
python -c "from test_agents.prompts.loader import load_prompt; print(load_prompt('intent_classifier', user_request='hello')[:100])"
```

Expected: Prints the first 100 characters of the prompt with `{user_request}` replaced by `hello`.

- [ ] **Step 3: Commit**

```bash
git add test_agents/prompts/intent_classifier.md
git commit -m "feat(prompts): add intent_classifier prompt template"
```

---

### Task 3: Create reply.md prompt template

**Files:**
- Create: `test_agents/prompts/reply.md`

- [ ] **Step 1: Create prompt file**

```markdown
你是 Test Agents 系统的客服助手。根据意图分类结果，生成一段友好、自然的回复。

## 分类说明

- `irrelevant`：用户需求与系统能力完全无关。回复应礼貌说明系统能力范围，并举例说明可以处理的请求格式。
- `ambiguous`：用户需求可能与系统能力相关，但信息不足。回复应表示理解用户可能有相关需求，但请补充具体信息（模块名、commit 范围、测试用例内容等）。

## 输入

- 用户需求：{user_request}
- 分类结果：{classification}
- 分类理由：{reason}

## 输出要求

- 语气友好、专业
- 直接给出回复内容，不要输出 JSON 或 markdown 代码块
- irrelevant 回复控制在 3-5 句话
- ambiguous 回复控制在 2-3 句话，明确列出需要补充的信息

## 示例

### irrelevant 示例
用户需求："今天天气怎样？"
分类：irrelevant
回复：
您好！我是 Test Agents，专门用于分析代码变更和评审测试用例。我可以帮您分析模块的 git diff 或评审测试用例质量。如果您有代码分析需求，请告诉我模块名和 commit 范围。

### ambiguous 示例
用户需求："帮我看看测试"
分类：ambiguous
回复：
好的，我可以帮您评审测试用例。请补充以下信息：1）需要分析的模块名称；2）代码变更的 commit 范围（如有）；3）需要评审的具体测试用例内容。
```

- [ ] **Step 2: Verify prompt loads correctly**

```python
python -c "from test_agents.prompts.loader import load_prompt; print(load_prompt('reply', user_request='hello', classification='irrelevant', reason='打招呼')[:100])"
```

Expected: Prints first 100 chars with variables replaced.

- [ ] **Step 3: Commit**

```bash
git add test_agents/prompts/reply.md
git commit -m "feat(prompts): add reply prompt template for irrelevant/ambiguous requests"
```

---

### Task 4: Implement intent_classifier_node and reply_node in supervisor.py

**Files:**
- Modify: `test_agents/agents/supervisor.py`

- [ ] **Step 1: Write the failing test**

Add to `test_agents/tests/test_supervisor.py`:

```python
class TestIntentClassifierNode:
    def test_classifies_relevant(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"classification": "relevant", "reason": "明确需求"}')
        state: SupervisorState = {"user_request": "分析 payment 模块代码变更", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = intent_classifier_node(state)
        assert result["intent_classification"] == "relevant"
        assert result["intent_reason"] == "明确需求"

    def test_classifies_irrelevant(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"classification": "irrelevant", "reason": "打招呼"}')
        state: SupervisorState = {"user_request": "hello", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = intent_classifier_node(state)
        assert result["intent_classification"] == "irrelevant"
        assert result["intent_reason"] == "打招呼"

    def test_fallback_to_ambiguous_on_invalid_json(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="not json at all")
        state: SupervisorState = {"user_request": "test", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = intent_classifier_node(state)
        assert result["intent_classification"] == "ambiguous"
        assert "解析失败" in result["intent_reason"]

    def test_fallback_to_ambiguous_on_llm_exception(self):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("network error")
        state: SupervisorState = {"user_request": "test", "messages": []}
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = intent_classifier_node(state)
        assert result["intent_classification"] == "ambiguous"


class TestReplyNode:
    def test_reply_generates_final_answer(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="您好！我是 Test Agents...")
        state: SupervisorState = {
            "user_request": "hello",
            "intent_classification": "irrelevant",
            "intent_reason": "打招呼",
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = reply_node(state)
        assert result["final_answer"] == "您好！我是 Test Agents..."

    def test_reply_fallback_on_llm_exception(self):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("network error")
        state: SupervisorState = {
            "user_request": "hello",
            "intent_classification": "irrelevant",
            "intent_reason": "打招呼",
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = reply_node(state)
        assert "Test Agents" in result["final_answer"]

    def test_reply_fallback_on_ambiguous(self):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("timeout")
        state: SupervisorState = {
            "user_request": "帮我看看测试",
            "intent_classification": "ambiguous",
            "intent_reason": "信息不足",
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = reply_node(state)
        assert "请补充" in result["final_answer"]
```

Also add imports at top of test file:
```python
from test_agents.agents.supervisor import (
    ...,
    intent_classifier_node,
    reply_node,
    route_from_classifier,
)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_agents/tests/test_supervisor.py::TestIntentClassifierNode -v`

Expected: FAIL with `NameError: name 'intent_classifier_node' is not defined`

- [ ] **Step 3: Implement intent_classifier_node**

In `test_agents/agents/supervisor.py`, after `get_llm()` function, add:

```python
def intent_classifier_node(state: SupervisorState) -> dict:
    """Classify user request intent before entering planner."""
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
    except (json.JSONDecodeError, Exception):
        classification = "ambiguous"
        reason = "意图分类解析失败，默认按模糊请求处理"

    return {
        "intent_classification": classification,
        "intent_reason": reason,
    }
```

- [ ] **Step 4: Implement reply_node**

In `test_agents/agents/supervisor.py`, after `intent_classifier_node`, add:

```python
def reply_node(state: SupervisorState) -> dict:
    """Generate friendly reply for irrelevant or ambiguous requests."""
    llm = get_llm()
    user_request = state.get("user_request", "")
    classification = state.get("intent_classification", "ambiguous")
    reason = state.get("intent_reason", "")

    prompt = load_prompt(
        "reply",
        user_request=user_request,
        classification=classification,
        reason=reason,
    )

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return {"final_answer": response.content}
    except Exception:
        # 降级到硬编码回复模板，确保流程不中断
        if classification == "irrelevant":
            fallback = (
                "您好！我是 Test Agents，专门用于分析代码变更和评审测试用例。"
                "如果您有代码分析需求，请告诉我模块名和 commit 范围。"
            )
        else:
            fallback = (
                "好的，我可以帮您评审测试用例。请补充以下信息："
                "1）需要分析的模块名称；2）代码变更的 commit 范围（如有）；"
                "3）需要评审的具体测试用例内容。"
            )
        return {"final_answer": fallback}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest test_agents/tests/test_supervisor.py::TestIntentClassifierNode test_agents/tests/test_supervisor.py::TestReplyNode -v`

Expected: All 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add test_agents/agents/supervisor.py test_agents/tests/test_supervisor.py
git commit -m "feat(supervisor): add intent_classifier_node and reply_node"
```

---

### Task 5: Add route_from_classifier

**Files:**
- Modify: `test_agents/agents/supervisor.py`
- Modify: `test_agents/tests/test_supervisor.py`

- [ ] **Step 1: Write the failing test**

Add to `test_agents/tests/test_supervisor.py`:

```python
class TestRouteFromClassifier:
    def test_relevant_goes_planner(self):
        state: SupervisorState = {"intent_classification": "relevant"}
        assert route_from_classifier(state) == "planner"

    def test_ambiguous_goes_reply(self):
        state: SupervisorState = {"intent_classification": "ambiguous"}
        assert route_from_classifier(state) == "reply"

    def test_irrelevant_goes_reply(self):
        state: SupervisorState = {"intent_classification": "irrelevant"}
        assert route_from_classifier(state) == "reply"

    def test_empty_defaults_to_reply(self):
        state: SupervisorState = {"intent_classification": ""}
        assert route_from_classifier(state) == "reply"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_agents/tests/test_supervisor.py::TestRouteFromClassifier -v`

Expected: FAIL with `NameError`

- [ ] **Step 3: Implement route_from_classifier**

In `test_agents/agents/supervisor.py`, before `route_from_confirm`, add:

```python
def route_from_classifier(state: SupervisorState) -> Literal["planner", "reply"]:
    """Route after intent_classifier: relevant→planner, ambiguous/irrelevant→reply"""
    classification = state.get("intent_classification", "")
    if classification == "relevant":
        return "planner"
    return "reply"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_agents/tests/test_supervisor.py::TestRouteFromClassifier -v`

Expected: All 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add test_agents/agents/supervisor.py test_agents/tests/test_supervisor.py
git commit -m "feat(supervisor): add route_from_classifier"
```

---

### Task 6: Wire new nodes into graph builder

**Files:**
- Modify: `test_agents/graph/builder.py`

- [ ] **Step 1: Update imports**

Change the import block in `test_agents/graph/builder.py`:

```python
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
    route_from_classifier,
    intent_classifier_node,
    reply_node,
    get_llm,
)
```

- [ ] **Step 2: Add nodes and update edges**

In `build_graph()`, after existing `graph.add_node` calls, add:

```python
graph.add_node("intent_classifier", intent_classifier_node)
graph.add_node("reply", reply_node)
```

Replace the START edge:
```python
# Old:
graph.add_edge(START, "planner")

# New:
graph.add_edge(START, "intent_classifier")
```

Add conditional edges for intent_classifier:
```python
graph.add_conditional_edges(
    "intent_classifier",
    route_from_classifier,
    {"planner": "planner", "reply": "reply"},
)
```

Add edge from reply to END:
```python
graph.add_edge("reply", END)
```

- [ ] **Step 3: Verify graph compiles**

Run: `python -c "from test_agents.graph.builder import build_graph; app = build_graph(); print('Graph compiled successfully')"`

Expected: `Graph compiled successfully`

- [ ] **Step 4: Commit**

```bash
git add test_agents/graph/builder.py
git commit -m "feat(builder): wire intent_classifier and reply nodes into graph"
```

---

### Task 7: Update main.py initial state

**Files:**
- Modify: `test_agents/main.py`

- [ ] **Step 1: Add new fields to _build_initial_state**

In `_build_initial_state()`, add:

```python
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
        "max_plan_iterations": config.MAX_PLAN_ITERATIONS,
        "plan_iterations": 0,
        "confirm_retry_count": 0,
        "max_confirm_retries": config.MAX_CONFIRM_RETRIES,
        "final_answer": None,
        "messages": [],
        "intent_classification": "",
        "intent_reason": "",
    }
```

- [ ] **Step 2: Verify main still runs**

Run: `python -c "from test_agents.main import _build_initial_state; s = _build_initial_state('test'); assert s['intent_classification'] == ''"`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add test_agents/main.py
git commit -m "feat(main): add intent fields to initial state"
```

---

### Task 8: Add end-to-end integration tests

**Files:**
- Modify: `test_agents/tests/test_integration.py`

- [ ] **Step 1: Write end-to-end test for irrelevant request**

Add to `test_agents/tests/test_integration.py`:

```python
def test_irrelevant_request_skips_planner():
    """End-to-end: irrelevant request should go intent_classifier → reply → END without planner"""
    mock_classifier_response = MagicMock()
    mock_classifier_response.content = '{"classification": "irrelevant", "reason": "打招呼"}'

    mock_reply_response = MagicMock()
    mock_reply_response.content = "您好！我是 Test Agents，专门用于分析代码变更..."

    with patch("test_agents.agents.supervisor.get_llm") as mock_supervisor_llm:
        mock_llm_instance = MagicMock()
        mock_supervisor_llm.return_value = mock_llm_instance
        mock_llm_instance.invoke.side_effect = [
            mock_classifier_response,
            mock_reply_response,
        ]

        result = run_test_agents("hello")

    assert result.get("final_answer") == "您好！我是 Test Agents，专门用于分析代码变更..."
    assert "plan" not in result or result.get("plan") is None
```

- [ ] **Step 2: Write end-to-end test for ambiguous request**

```python
def test_ambiguous_request_gets_clarification():
    """End-to-end: ambiguous request should get a reply asking for more info"""
    mock_classifier_response = MagicMock()
    mock_classifier_response.content = '{"classification": "ambiguous", "reason": "信息不足"}'

    mock_reply_response = MagicMock()
    mock_reply_response.content = "请补充模块名和 commit 范围..."

    with patch("test_agents.agents.supervisor.get_llm") as mock_supervisor_llm:
        mock_llm_instance = MagicMock()
        mock_supervisor_llm.return_value = mock_llm_instance
        mock_llm_instance.invoke.side_effect = [
            mock_classifier_response,
            mock_reply_response,
        ]

        result = run_test_agents("帮我看看测试")

    assert result.get("final_answer") == "请补充模块名和 commit 范围..."
```

- [ ] **Step 3: Write end-to-end test for relevant request (existing flow preserved)**

```python
def test_relevant_request_goes_full_pipeline():
    """End-to-end: relevant request should still go through full plan-and-solve flow"""
    mock_classifier_response = MagicMock()
    mock_classifier_response.content = '{"classification": "relevant", "reason": "明确需求"}'

    plan_json = json.dumps({
        "intent": "测试订单模块",
        "steps": [
            {"agent": "code_analyzer", "step_id": 1, "description": "分析订单模块", "input_mapping": {}, "output_key": "code_change_report"},
        ],
        "confirmed": False,
    }, ensure_ascii=False)
    mock_planner_response = MagicMock()
    mock_planner_response.content = plan_json

    mock_reflect_response = MagicMock()
    mock_reflect_response.content = '{"assessment": "COMPLETE", "feedback": ""}'

    mock_synthesize_response = MagicMock()
    mock_synthesize_response.content = "分析完成"

    mock_code_analyzer_result = {
        "outputs": {"code_change_report": "代码变更分析完成"},
        "current_step_index": 1,
        "step_results": [{"step_id": 1, "agent": "code_analyzer", "status": "success", "output_key": "code_change_report"}],
    }

    with patch("test_agents.agents.supervisor.get_llm") as mock_supervisor_llm, \
         patch("test_agents.graph.builder.get_llm") as mock_builder_llm, \
         patch("test_agents.agents.supervisor.interrupt") as mock_interrupt, \
         patch("test_agents.graph.builder.code_analyzer_wrapper") as mock_code_analyzer_wrapper:

        mock_llm_instance = MagicMock()
        mock_supervisor_llm.return_value = mock_llm_instance
        mock_builder_llm.return_value = mock_llm_instance

        mock_llm_instance.invoke.side_effect = [
            mock_classifier_response,
            mock_planner_response,
            mock_reflect_response,
            mock_synthesize_response,
        ]

        mock_interrupt.return_value = {"confirmed": True}
        mock_code_analyzer_wrapper.return_value = mock_code_analyzer_result

        result = run_test_agents("分析订单模块代码变更")

    assert result.get("outputs", {}).get("code_change_report") == "代码变更分析完成"
    assert result.get("final_answer") == "分析完成"
```

- [ ] **Step 4: Run all integration tests**

Run: `pytest test_agents/tests/test_integration.py -v`

Expected: All tests pass, including new ones.

- [ ] **Step 5: Commit**

```bash
git add test_agents/tests/test_integration.py
git commit -m "test(integration): add e2e tests for intent classifier flow"
```

---

### Task 9: Run full test suite

- [ ] **Step 1: Run all tests**

```bash
python -m pytest test_agents/tests/ -v
```

Expected: All tests pass.

- [ ] **Step 2: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix: address test failures from intent classifier integration"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] `intent_classifier_node` with LLM call and JSON parsing — Task 4
- [x] Fallback to `ambiguous` on parse/LLM failure — Task 4, tests
- [x] `reply_node` with prompt-based reply generation — Task 4
- [x] `reply_node` LLM 异常降级到硬编码模板 — Task 4
- [x] `route_from_classifier` routing logic — Task 5
- [x] Graph builder wiring (START → intent_classifier → route → planner/reply) — Task 6
- [x] New state fields in `SupervisorState` — Task 1
- [x] Prompt files (`intent_classifier.md`, `reply.md`) — Tasks 2-3
- [x] End-to-end tests for all three classifications — Task 8

**Placeholder scan:**
- [x] No "TBD" or "TODO" in plan
- [x] All test code contains actual assertions
- [x] All file paths are exact

**Type consistency:**
- [x] `intent_classification` field used consistently as `str` across all tasks
- [x] `intent_reason` field used consistently as `str`
- [x] `route_from_classifier` returns `Literal["planner", "reply"]` matching builder wiring

## 审查跟进（/autoplan 遗留）

以下问题在本次实施中已部分处理，但仍有后续工作：

| # | 问题 | 本次处理 | 后续行动 |
|---|---|---|---|
| 1 | `reply_node` LLM 异常导致流程崩溃 | 已添加 try/except + 硬编码降级模板（Task 4） | 后续可优化为按分类加载不同 prompt 模板作为降级 |
| 2 | `main.py` 关键字匹配器与 `intent_classifier_node` 职责重叠 | 未修改，保留现有 direct worker 调用 | 未来考虑统一入口路由层（TODOS） |
| 3 | `ambiguous` 分类只能生成静态回复，不支持多轮澄清 | 未修改 | 未来考虑支持用户在收到 ambiguous 回复后继续补充信息（TODOS） |
| 4 | 非法 classification 值（非 relevant/ambiguous/irrelevant） | `intent_classifier_node` 中已做校验，非法值回退到 ambiguous | 无需后续行动 |
