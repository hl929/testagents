# Universal Outputs Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fixed result fields (`code_change_report`, `review_results`) in `SupervisorState` with a generic `outputs: dict` field, add `output_key` to `PlanStep`, update all Worker wrappers to write into `outputs`, and update `synthesize_node` to iterate over `outputs` dynamically.

**Architecture:** Workers no longer return hardcoded field names. Each `PlanStep` declares an `output_key`. Workers read existing `outputs` from state, write their result under that key, and return the full `outputs` dict. LangGraph's `operator.or_` reducer merges dict updates. `synthesize_node` renders all `outputs` entries into the LLM prompt.

**Tech Stack:** Python 3.11+, LangGraph, Pydantic, pytest

---

## Implementation Status

| Task | Status | Commit |
|---|---|---|
| Task 1: Add `outputs` to `SupervisorState` and `output_key` to `PlanStep` | ✅ Completed | `e04ea80` |
| Task 2: Update `_resolve_input` for `${outputs.xxx}` | ✅ Completed | `13a77e8` |
| Task 3: Update `code_analyzer_wrapper` for `outputs` | ✅ Completed | `2fb5ed6` |
| Task 4: Update `case_reviewer_wrapper` for `outputs` | ✅ Completed | `0e7d566` |
| Task 5: Update `synthesize_node` for `outputs` | ✅ Completed | `0e7d566` |
| Task 6: Update Prompt Templates | ✅ Completed | `5056969` |
| Task 7: Fix Integration Tests | ✅ Completed | `5056969` |
| Task 8: Full Test Suite Validation | ✅ Completed | No changes needed (76 passed, 0 failed) |

**Test Results:** 76 passed, 0 failed

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `test_agents/graph/state.py` | Modify | Add `outputs` to `SupervisorState`, add `output_key` to `PlanStep` |
| `test_agents/agents/code_analyzer.py` | Modify | Wrapper writes result into `outputs[output_key]` instead of `code_change_report` |
| `test_agents/agents/case_reviewer.py` | Modify | Wrapper writes result into `outputs[output_key]`; `_resolve_input` supports `${outputs.xxx}` |
| `test_agents/agents/supervisor.py` | Modify | `synthesize_node` iterates over `outputs` instead of hardcoded fields |
| `test_agents/prompts/planner.md` | Modify | Add `output_key` to the PlanStep spec table and rules |
| `test_agents/prompts/synthesize.md` | Modify | Replace hardcoded result fields with `{outputs}` variable |
| `test_agents/tests/test_state.py` | Modify | Assert `PlanStep.output_key` exists; assert `SupervisorState` accepts `outputs` |
| `test_agents/tests/test_workers.py` | Modify | Assert wrappers return `outputs` dict |
| `test_agents/tests/test_supervisor.py` | Modify | Assert `synthesize_node` reads from `outputs` |
| `test_agents/tests/test_integration.py` | Modify | Mock results use `outputs` instead of fixed fields |

---

## Task 1: Add `outputs` to `SupervisorState` and `output_key` to `PlanStep`

**Files:**
- Modify: `test_agents/graph/state.py`
- Test: `test_agents/tests/test_state.py`

### Step 1: Write failing test for `PlanStep.output_key`

Add to `test_agents/tests/test_state.py`, inside `TestPlanStep`:

```python
    def test_output_key_field(self):
        step = PlanStep(
            step_id=1,
            agent="code_analyzer",
            description="分析代码",
            input_mapping={},
            output_key="code_change_report",
        )
        assert step.output_key == "code_change_report"

    def test_output_key_defaults_to_empty_string(self):
        step = PlanStep(step_id=1, agent="code_analyzer", description="test")
        assert step.output_key == ""
```

### Step 2: Run test to verify it fails

```bash
python -m pytest test_agents/tests/test_state.py::TestPlanStep::test_output_key_field -v
```
Expected: FAIL with `unexpected keyword argument 'output_key'`

### Step 3: Add `output_key` to `PlanStep`

In `test_agents/graph/state.py`, modify `PlanStep`:

```python
class PlanStep(BaseModel):
    step_id: int = Field(description="步骤序号，从 1 开始")
    agent: str = Field(description="执行 agent: code_analyzer / case_reviewer")
    description: str = Field(description="步骤描述")
    input_mapping: dict[str, str] = Field(default_factory=dict, description="agent入参 → state字段引用或常量")
    output_key: str = Field(default="", description="结果写入 outputs 的 key，空则按 agent 类型默认")
```

### Step 4: Run tests to verify they pass

```bash
python -m pytest test_agents/tests/test_state.py::TestPlanStep -v
```
Expected: PASS

### Step 5: Write failing test for `SupervisorState` with `outputs`

Add to `test_agents/tests/test_state.py`, inside `TestExecutionPlan` or as a new class:

```python
class TestSupervisorStateOutputs:
    def test_outputs_field_accepted(self):
        state: SupervisorState = {
            "user_request": "test",
            "outputs": {"code_change_report": "report content"},
        }
        assert state["outputs"]["code_change_report"] == "report content"

    def test_outputs_defaults_to_empty_dict(self):
        state: SupervisorState = {"user_request": "test"}
        assert state.get("outputs", {}) == {}
```

### Step 6: Run test to verify it fails

```bash
python -m pytest test_agents/tests/test_state.py::TestSupervisorStateOutputs -v
```
Expected: PASS (TypedDict allows extra keys at runtime, so this should actually pass already, but we keep it as documentation)

### Step 7: Add `outputs` to `SupervisorState`

In `test_agents/graph/state.py`, modify `SupervisorState`:

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
    outputs: Annotated[dict, operator.or_]   # ADD THIS LINE
    code_change_report: str
    review_results: list[dict]
    final_answer: Optional[str]
    messages: Annotated[list[AnyMessage], add_messages]
```

### Step 8: Run tests to verify

```bash
python -m pytest test_agents/tests/test_state.py -v
```
Expected: PASS

### Step 9: Commit

```bash
git add test_agents/graph/state.py test_agents/tests/test_state.py
git commit -m "feat(state): add outputs dict and output_key field

- Add outputs: Annotated[dict, operator.or_] to SupervisorState
- Add output_key field to PlanStep with empty string default
- Add tests for new fields

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Update `_resolve_input` to support `${outputs.xxx}` references

**Files:**
- Modify: `test_agents/agents/case_reviewer.py`
- Test: `test_agents/tests/test_integration.py` (existing `_resolve_input` tests)

### Step 1: Write failing test

Add to `test_agents/tests/test_integration.py`, inside `test_resolve_input`:

```python
    # Test case: outputs reference
    state = {
        "outputs": {"code_change_report": "报告内容", "review_results": [{"id": "1"}]},
        "user_request": "test"
    }
    assert _resolve_input("${outputs.code_change_report}", state) == "报告内容"
    assert _resolve_input("${outputs.review_results}", state) == '[{"id": "1"}]'

    # Test case: missing outputs key returns empty string
    assert _resolve_input("${outputs.nonexistent}", state) == ""

    # Test case: outputs reference when outputs is missing
    assert _resolve_input("${outputs.code_change_report}", {}) == ""
```

### Step 2: Run test to verify it fails

```bash
python -m pytest test_agents/tests/test_integration.py::test_resolve_input -v
```
Expected: FAIL — outputs references return empty string or wrong values

### Step 3: Implement `_resolve_input` with outputs support

In `test_agents/agents/case_reviewer.py`, replace the existing `_resolve_input`:

```python
def _resolve_input(value: str, state: SupervisorState) -> str:
    """Resolve input_mapping value: ${field} → state field, ${outputs.key} → outputs dict, otherwise constant"""
    if not (value.startswith("${") and value.endswith("}")):
        return value

    path = value[2:-1]  # e.g., "code_change_report" or "outputs.code_change_report"

    if path.startswith("outputs."):
        outputs = state.get("outputs", {})
        key = path[8:]  # Remove "outputs." prefix
        val = outputs.get(key, "")
    else:
        val = state.get(path, "")

    return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
```

### Step 4: Run test to verify it passes

```bash
python -m pytest test_agents/tests/test_integration.py::test_resolve_input -v
```
Expected: PASS

### Step 5: Commit

```bash
git add test_agents/agents/case_reviewer.py test_agents/tests/test_integration.py
git commit -m "feat(case_reviewer): _resolve_input supports ${outputs.xxx} references

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Update `code_analyzer_wrapper` to write into `outputs`

**Files:**
- Modify: `test_agents/agents/code_analyzer.py`
- Test: `test_agents/tests/test_workers.py`

### Step 1: Write failing test

Add to `test_agents/tests/test_workers.py`, inside `TestCodeAnalyzerGraph`:

```python
    def test_code_analyzer_wrapper_writes_to_outputs(self):
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
                     "input_mapping": {"module_name": "payment", "source_commit": "abc1234", "target_commit": "def5678"},
                     "output_key": "code_change_report"},
                ],
                "confirmed": True,
            },
            "current_step_index": 0,
            "step_results": [],
            "messages": [],
        }
        with patch("test_agents.agents.code_analyzer.code_analyzer_graph", mock_graph):
            result = code_analyzer_wrapper(state)
        assert "outputs" in result
        assert "code_change_report" in result["outputs"]
        assert "变更概述" in result["outputs"]["code_change_report"]
        assert result["current_step_index"] == 1
```

### Step 2: Run test to verify it fails

```bash
python -m pytest test_agents/tests/test_workers.py::TestCodeAnalyzerGraph::test_code_analyzer_wrapper_writes_to_outputs -v
```
Expected: FAIL — KeyError or assertion on `"outputs" not in result`

### Step 3: Implement wrapper to write into `outputs`

In `test_agents/agents/code_analyzer.py`, replace the return section of `code_analyzer_wrapper`:

```python
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

    output_key = step.get("output_key", "") or "code_change_report"

    task_desc = step.get("description", "")
    worker_input: WorkerState = {
        "task": task_desc,
        "messages": [HumanMessage(content=f"分析模块 {module_name} 的代码变更，commit 范围: {source_commit}..{target_commit}")],
        "error": "no",
        "reflection_count": 0,
        "max_reflections": 0,
        "output_key": output_key,
        "result": "",
    }

    if code_analyzer_graph is None:
        raise RuntimeError("code_analyzer_graph not initialized. Call build_code_analyzer_graph first.")

    result = code_analyzer_graph.invoke(worker_input)

    report = result.get("result", "")
    if not report:
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                report = msg.content
                break

    outputs = state.get("outputs", {}).copy()
    existing = outputs.get(output_key, "")
    if existing and module_name:
        report = existing + f"\n\n## 模块: {module_name}\n" + report
    outputs[output_key] = report

    return {
        "outputs": outputs,
        "current_step_index": current_index + 1,
        "step_results": [{
            "step_id": step.get("step_id", 0),
            "agent": step.get("agent", ""),
            "status": "success" if report else "failed",
            "output_key": output_key,
            "error": "" if report else "Empty result",
        }],
    }
```

### Step 4: Run tests to verify

```bash
python -m pytest test_agents/tests/test_workers.py::TestCodeAnalyzerGraph -v
```
Expected: PASS

### Step 5: Commit

```bash
git add test_agents/agents/code_analyzer.py test_agents/tests/test_workers.py
git commit -m "feat(code_analyzer): wrapper writes result into outputs[output_key]

- Read output_key from PlanStep, default to code_change_report
- Read existing outputs from state, merge new result
- Return outputs dict instead of hardcoded code_change_report field
- Update step_results to use dynamic output_key

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Update `case_reviewer_wrapper` to write into `outputs`

**Files:**
- Modify: `test_agents/agents/case_reviewer.py`
- Test: `test_agents/tests/test_workers.py`

### Step 1: Write failing test

Add to `test_agents/tests/test_workers.py`, inside `TestCaseReviewerGraph`:

```python
    def test_case_reviewer_wrapper_writes_to_outputs(self):
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
                     "input_mapping": {"code_change_report": "${outputs.code_change_report}"},
                     "output_key": "review_results"},
                ],
                "confirmed": True,
            },
            "current_step_index": 0,
            "outputs": {"code_change_report": "变更报告"},
            "step_results": [],
            "messages": [],
        }
        with patch("test_agents.agents.case_reviewer.case_reviewer_graph", mock_graph):
            result = case_reviewer_wrapper(state)
        assert "outputs" in result
        assert "review_results" in result["outputs"]
        assert result["outputs"]["review_results"][0]["case_id"] == "TC001"
        assert result["current_step_index"] == 1
```

### Step 2: Run test to verify it fails

```bash
python -m pytest test_agents/tests/test_workers.py::TestCaseReviewerGraph::test_case_reviewer_wrapper_writes_to_outputs -v
```
Expected: FAIL

### Step 3: Implement wrapper to write into `outputs`

In `test_agents/agents/case_reviewer.py`, replace the return section of `case_reviewer_wrapper`:

```python
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

    output_key = step.get("output_key", "") or "review_results"

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
        "output_key": output_key,
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

    outputs = state.get("outputs", {}).copy()
    outputs[output_key] = review_results

    return {
        "outputs": outputs,
        "current_step_index": current_index + 1,
        "step_results": [{
            "step_id": step.get("step_id", 0),
            "agent": step.get("agent", ""),
            "status": "success" if review_results else "failed",
            "output_key": output_key,
            "error": "" if review_results else "Empty result",
        }],
    }
```

### Step 4: Run tests to verify

```bash
python -m pytest test_agents/tests/test_workers.py::TestCaseReviewerGraph -v
```
Expected: PASS

### Step 5: Commit

```bash
git add test_agents/agents/case_reviewer.py test_agents/tests/test_workers.py
git commit -m "feat(case_reviewer): wrapper writes result into outputs[output_key]

- Read output_key from PlanStep, default to review_results
- _resolve_input now supports ${outputs.xxx} syntax
- Read existing outputs from state, merge new result
- Return outputs dict instead of hardcoded review_results field
- Update step_results to use dynamic output_key

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Update `synthesize_node` to iterate over `outputs`

**Files:**
- Modify: `test_agents/agents/supervisor.py`
- Test: `test_agents/tests/test_supervisor.py`

### Step 1: Write failing test

Add to `test_agents/tests/test_supervisor.py`, inside `TestSynthesizeNode`:

```python
    def test_synthesize_reads_from_outputs(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="基于 outputs 的综合报告")
        state: SupervisorState = {
            "user_request": "test",
            "plan": {"intent": "test", "steps": []},
            "step_results": [{"step_id": 1, "status": "success"}],
            "outputs": {"code_change_report": "变更内容", "review_results": [{"verdict": "pass"}]},
            "messages": [],
        }
        with patch("test_agents.agents.supervisor.get_llm", return_value=mock_llm):
            result = synthesize_node(state)
        assert result["final_answer"] == "基于 outputs 的综合报告"
        # Verify prompt contains outputs content
        prompt_arg = mock_llm.invoke.call_args[0][0][0].content
        assert "【code_change_report】" in prompt_arg
        assert "变更内容" in prompt_arg
```

### Step 2: Run test to verify it fails

```bash
python -m pytest test_agents/tests/test_supervisor.py::TestSynthesizeNode::test_synthesize_reads_from_outputs -v
```
Expected: FAIL — prompt does not contain outputs markers

### Step 3: Implement `synthesize_node` with outputs iteration

In `test_agents/agents/supervisor.py`, replace `synthesize_node`:

```python
def synthesize_node(state: SupervisorState) -> dict:
    """Synthesize all step results into final answer"""
    llm = get_llm()
    user_request = state.get("user_request", "")
    plan = state.get("plan", {})
    step_results = state.get("step_results", [])
    outputs = state.get("outputs", {})

    plan_summary = json.dumps(plan.get("steps", []), ensure_ascii=False)
    step_results_summary = json.dumps(step_results, ensure_ascii=False)

    output_summaries = []
    for key, value in outputs.items():
        summary = f"【{key}】\n{str(value)[:3000]}"
        output_summaries.append(summary)

    prompt = load_prompt(
        "synthesize",
        user_request=user_request,
        plan_summary=plan_summary,
        step_results_summary=step_results_summary,
        outputs="\n\n---\n\n".join(output_summaries),
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"final_answer": response.content}
```

### Step 4: Run tests to verify

```bash
python -m pytest test_agents/tests/test_supervisor.py::TestSynthesizeNode -v
```
Expected: PASS

### Step 5: Commit

```bash
git add test_agents/agents/supervisor.py test_agents/tests/test_supervisor.py
git commit -m "feat(supervisor): synthesize_node iterates over outputs dynamically

- Replace hardcoded field references with dynamic outputs iteration
- Render each output key as a section in the prompt
- Pass {outputs} variable to synthesize prompt template

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Update Prompt Templates

**Files:**
- Modify: `test_agents/prompts/planner.md`
- Modify: `test_agents/prompts/synthesize.md`

### Step 1: Update `planner.md`

In `test_agents/prompts/planner.md`, update the `PlanStep` table and rules:

**Add to `input_mapping` 规则下方：**

```markdown
### output_key 规则

每个步骤必须指定 `output_key`，表示该步骤的执行结果写入 `outputs` 字典的哪个 key：
- `code_analyzer` 默认使用 `"code_change_report"`
- `case_reviewer` 默认使用 `"review_results"`
- 多模块分析时，可为每个模块分配独立的 `output_key`（如 `"report_payment"`、`"report_order"`）
- 同 `output_key` 的多次执行会自动拼接结果
```

**更新示例 JSON：**

在示例的 `steps` 中每个 step 添加 `"output_key"`：

```json
    {
      "step_id": 1,
      "agent": "code_analyzer",
      "description": "分析 payment 模块从 abc1234 到 def5678 的代码变更",
      "output_key": "code_change_report",
      "input_mapping": {
        "module_name": "payment",
        "source_commit": "abc1234",
        "target_commit": "def5678"
      }
    },
    {
      "step_id": 2,
      "agent": "case_reviewer",
      "description": "基于代码变更报告评审测试用例",
      "output_key": "review_results",
      "input_mapping": {
        "code_change_report": "${outputs.code_change_report}",
        "test_cases": "",
        "business_knowledge": ""
      }
    }
```

### Step 2: Update `synthesize.md`

In `test_agents/prompts/synthesize.md`, replace the result section:

```markdown
## 各 Agent 产出结果
{outputs}
```

Remove the old `## 各步骤结果` and `{step_results_summary}` line if they were the only result source, or keep `step_results_summary` alongside `outputs`.

The final `synthesize.md` should look like:

```markdown
你是结果汇总专家。请基于以下执行结果，综合回答用户的原始需求。

## 用户原始需求
{user_request}

## 执行计划
{plan_summary}

## 各步骤执行状态
{step_results_summary}

## 各 Agent 产出结果
{outputs}

## 输出要求

请生成最终的综合分析报告，直接回答用户需求。报告应包含：
1. 需求理解摘要
2. 各步骤关键发现
3. 综合结论和建议
```

### Step 3: Commit

```bash
git add test_agents/prompts/planner.md test_agents/prompts/synthesize.md
git commit -m "docs(prompts): update planner and synthesize for outputs mechanism

- Add output_key rules and examples to planner.md
- Replace hardcoded result fields with {outputs} variable in synthesize.md

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Fix Integration Tests

**Files:**
- Modify: `test_agents/tests/test_integration.py`

### Step 1: Update mock results to use `outputs`

In `test_agents/tests/test_integration.py`, in `test_full_pipeline_mocked`, replace the worker mock returns:

```python
    mock_code_analyzer_result = {
        "outputs": {"code_change_report": "代码变更分析完成"},
        "current_step_index": 1,
        "step_results": [
            {"step_id": 1, "agent": "code_analyzer", "status": "success", "output_key": "code_change_report"}
        ]
    }
    mock_case_reviewer_result = {
        "outputs": {"review_results": [{"case_id": "TC001", "verdict": "pass", "score": 90}]},
        "current_step_index": 2,
        "step_results": [
            {"step_id": 2, "agent": "case_reviewer", "status": "success", "output_key": "review_results"}
        ]
    }
```

Update the assertion block:

```python
        assert "outputs" in result
        assert "code_change_report" in result["outputs"]
        assert "review_results" in result["outputs"]
        assert "final_answer" in result
```

In `test_pipeline_with_simple_request`, update similarly:

```python
    mock_code_analyzer_result = {
        "outputs": {"code_change_report": "分析完成"},
        "current_step_index": 1,
        "step_results": [
            {"step_id": 1, "agent": "code_analyzer", "status": "success", "output_key": "code_change_report"}
        ]
    }
```

And the assertion:

```python
        assert "outputs" in result
        assert "code_change_report" in result["outputs"]
```

### Step 2: Run integration tests

```bash
python -m pytest test_agents/tests/test_integration.py -v
```
Expected: PASS

### Step 3: Commit

```bash
git add test_agents/tests/test_integration.py
git commit -m "test(integration): update mocks and assertions for outputs mechanism

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Full Test Suite Validation

**Files:**
- All test files

### Step 1: Run complete test suite

```bash
python -m pytest test_agents/tests/ -v
```

### Step 2: Fix any remaining failures

Common issues to watch for:
- Tests that construct `SupervisorState` dicts and reference `code_change_report` or `review_results` directly — update to use `outputs` wrapper
- Tests that assert on hardcoded field names in worker return dicts
- Tests that construct `PlanStep` without `output_key` — verify default value works

### Step 3: Commit

```bash
git commit -m "test: full test suite pass after outputs mechanism migration

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Spec Coverage Self-Review

| Spec Section | Implementing Task | Status |
|---|---|---|
| SupervisorState adds `outputs: Annotated[dict, operator.or_]` | Task 1 | ✅ |
| PlanStep adds `output_key: str` | Task 1 | ✅ |
| Worker wrapper reads `output_key` from step | Task 3, 4 | ✅ |
| Worker wrapper reads existing `outputs`, merges new result | Task 3, 4 | ✅ |
| Worker wrapper returns `outputs` dict | Task 3, 4 | ✅ |
| `_resolve_input` supports `${outputs.xxx}` | Task 2 | ✅ |
| `synthesize_node` iterates over `outputs` | Task 5 | ✅ |
| `planner.md` documents `output_key` | Task 6 | ✅ |
| `synthesize.md` uses `{outputs}` variable | Task 6 | ✅ |
| Multi-module aggregation via same `output_key` | Task 3 (existing logic preserved) | ✅ |
| Tests updated | Task 7, 8 | ✅ |

## Placeholder Scan

- No "TBD", "TODO", "implement later" found
- No vague "add error handling" without specifics
- All code blocks contain complete, runnable code
- All file paths are exact

## Type Consistency Check

- `output_key` used consistently as `str` across `PlanStep`, worker wrappers, and `StepResult`
- `outputs` used consistently as `dict` across `SupervisorState`, worker returns, and synthesize
- `_resolve_input` signature unchanged: `(value: str, state: SupervisorState) -> str`
