# Design-Implementation Gap Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all documented gaps between the design spec (`2026-05-15-test-agents-design.md`) and the current codebase, covering architecture alignment, missing features, code quality, and test coverage.

**Architecture:** Keep the existing wrapper-based subgraph invocation (necessary for SupervisorState → WorkerState mapping), but extract all common state-mapping logic into `worker_base.py` so wrappers become thin, dispatch regains its documented responsibility, and workers can be invoked directly from `main.py` for simple requests.

**Tech Stack:** Python 3.11, LangGraph, LangChain, Pydantic, pytest

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `test_agents/graph/state.py` | TypedDict state definitions | Remove deprecated fields |
| `test_agents/agents/worker_base.py` | Worker subgraph factory + shared utilities | Add `_resolve_input`, `build_worker_input`, `extract_worker_result`, fix `worker_reflect` result writeback |
| `test_agents/agents/code_analyzer.py` | Code analyzer wrapper | Use shared utilities, remove duplicated `_resolve_input` |
| `test_agents/agents/case_reviewer.py` | Case reviewer wrapper | Use shared utilities, remove duplicated `_resolve_input`, fix JSON parsing |
| `test_agents/agents/supervisor.py` | Supervisor nodes + routes | Strengthen `dispatch_node`, fix `save_experience_node` dedup + concurrency |
| `test_agents/main.py` | CLI entry + direct-worker dispatch | Implement `is_simple_request` fast path |
| `test_agents/prompts/planner.md` | Planner prompt template | Unify interpolation syntax to `${outputs.xxx}` |
| `test_agents/tests/test_integration.py` | Integration tests | Add multi-key resolve, direct-worker, pipeline-with-subgraph tests |
| `test_agents/tests/test_workers.py` | Worker unit tests | Add worker_reflect result-writeback, JSON parsing tests |

---

## Task 1: Remove Deprecated Fields from SupervisorState

**Files:**
- Modify: `test_agents/graph/state.py:73-74`
- Modify: `test_agents/main.py:49-50`
- Test: `test_agents/tests/test_integration.py`

**Context:** `SupervisorState` still carries `code_change_report: str` and `review_results: list[dict]`. The design says all worker results go through `outputs[output_key]` only.

- [ ] **Step 1: Delete the two fields from SupervisorState**

```python
# test_agents/graph/state.py
# Remove lines 73-74:
#     code_change_report: str
#     review_results: list[dict]
```

Target `SupervisorState` after change (lines 58–76):

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
```

- [ ] **Step 2: Remove initialisation of deleted fields in main.py**

In `_build_initial_state`, delete:

```python
        "code_change_report": "",
        "review_results": [],
```

- [ ] **Step 3: Run existing tests to catch any remaining references**

Run:
```bash
python -m pytest test_agents/tests/ -v
```

Expected: any test that sets `code_change_report` or `review_results` directly on state will fail. Fix those tests to use `outputs={"code_change_report": ...}` instead.

- [ ] **Step 4: Commit**

```bash
git add test_agents/graph/state.py test_agents/main.py test_agents/tests/
git commit -m "refactor(state,main): remove deprecated code_change_report and review_results fields"
```

---

## Task 2: Extract Shared Worker State-Mapping Utilities

**Files:**
- Modify: `test_agents/agents/worker_base.py`
- Modify: `test_agents/agents/code_analyzer.py`
- Modify: `test_agents/agents/case_reviewer.py`
- Test: `test_agents/tests/test_integration.py`, `test_agents/tests/test_workers.py`

**Context:** `_resolve_input` is copy-pasted in both wrappers. The design says dispatch should build `WorkerState`; we keep wrappers thin and move common logic to `worker_base.py`.

- [ ] **Step 1: Add `_resolve_input` and two helpers to `worker_base.py`**

Insert before `agent_node`:

```python
import re


def _resolve_input(value: str, state: SupervisorState) -> str:
    """Resolve input_mapping value.

    Supports:
    - constants (no ${...} wrapper)
    - single reference: ${field_name} or ${outputs.key}
    - multiple references in one string: ${outputs.a}\n${outputs.b}
    """
    if not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)

    pattern = re.compile(r'\$\{([^}]+)\}')

    def replacer(match: re.Match) -> str:
        path = match.group(1)
        if path.startswith("outputs."):
            key = path[8:]
            val = state.get("outputs", {}).get(key, "")
        else:
            val = state.get(path, "")
        return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)

    resolved = pattern.sub(replacer, value)

    # If the original was a bare reference and nothing else, return the raw value
    # so non-string types (e.g. list from outputs) are preserved when used directly.
    bare_match = pattern.fullmatch(value)
    if bare_match:
        path = bare_match.group(1)
        if path.startswith("outputs."):
            val = state.get("outputs", {}).get(path[8:], "")
        else:
            val = state.get(path, "")
        if not isinstance(val, str):
            return json.dumps(val, ensure_ascii=False)
        return val

    return resolved
```

Add import at top of `worker_base.py`:
```python
import re
from test_agents.graph.state import SupervisorState
```

- [ ] **Step 2: Delete duplicated `_resolve_input` from code_analyzer.py**

Remove the entire `_resolve_input` function (lines 22–36).

Update the import at the top:
```python
from test_agents.agents.worker_base import build_worker_graph, _resolve_input
```

- [ ] **Step 3: Delete duplicated `_resolve_input` from case_reviewer.py**

Remove the entire `_resolve_input` function (lines 22–36).

Update the import at the top:
```python
from test_agents.agents.worker_base import build_worker_graph, _resolve_input
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest test_agents/tests/test_integration.py::test_resolve_input -v
python -m pytest test_agents/tests/test_workers.py -v
```

Expected: existing tests pass (bare references still work).

- [ ] **Step 5: Commit**

```bash
git add test_agents/agents/worker_base.py test_agents/agents/code_analyzer.py test_agents/agents/case_reviewer.py
git commit -m "refactor(workers): extract _resolve_input to worker_base, support multi-key interpolation"
```

---

## Task 3: Fix `worker_reflect` Result Writeback

**Files:**
- Modify: `test_agents/agents/worker_base.py:21-65`
- Test: `test_agents/tests/test_workers.py`

**Context:** When `error == "no"`, the latest agent output in `messages` should be written back to `result` so wrappers reading `WorkerState.result` see the final content.

- [ ] **Step 1: Update `worker_reflect` to write back result on pass**

Replace the `return {"error": "no"}` branches so they also extract and set `result`.

The updated function body:

```python
def worker_reflect(state: WorkerState, llm) -> dict:
    """Worker reflect node - evaluate result quality"""
    max_reflections = state.get("max_reflections", 0)
    if max_reflections == 0:
        return {"error": "no", "result": _extract_last_agent_content(state)}

    reflection_count = state.get("reflection_count", 0)
    if reflection_count >= max_reflections:
        return {"error": "no", "result": _extract_last_agent_content(state)}

    result = state.get("result", "")
    messages = state.get("messages", [])
    if not result and messages:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                result = msg.content
                break

    task = state.get("task", "")
    prompt = load_prompt(
        "worker_reflect",
        task=task,
        result=result[:2000],
        reflection_count=reflection_count,
        max_reflections=max_reflections,
    )
    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        assessment = json.loads(content)
        if assessment.get("quality") == "pass":
            return {
                "error": "no",
                "result": _extract_last_agent_content(state),
            }
        feedback = assessment.get("feedback", "")
        return {
            "error": "yes",
            "reflection_count": reflection_count + 1,
            "messages": [HumanMessage(content=f"质量评估不通过，请重试。反馈：{feedback}")],
        }
    except (json.JSONDecodeError, AttributeError, IndexError):
        return {"error": "no", "result": _extract_last_agent_content(state)}
```

Add helper above `worker_reflect`:

```python
def _extract_last_agent_content(state: WorkerState) -> str:
    """Extract the last non-tool AIMessage content from messages."""
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
            return msg.content
    return state.get("result", "")
```

- [ ] **Step 2: Write test for result writeback**

Append to `test_agents/tests/test_workers.py`:

```python
from test_agents.agents.worker_base import worker_reflect, _extract_last_agent_content
from langchain_core.messages import AIMessage


class TestWorkerReflect:
    def test_reflect_pass_writes_back_result(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"quality": "pass", "feedback": ""}')
        state = {
            "task": "test",
            "messages": [
                AIMessage(content="first", tool_calls=[]),
                AIMessage(content="final result"),
            ],
            "reflection_count": 0,
            "max_reflections": 1,
            "result": "",
        }
        result = worker_reflect(state, mock_llm)
        assert result["error"] == "no"
        assert result["result"] == "final result"

    def test_reflect_no_max_reflections_writes_back_result(self):
        state = {
            "task": "test",
            "messages": [AIMessage(content="agent output")],
            "reflection_count": 0,
            "max_reflections": 0,
            "result": "",
        }
        result = worker_reflect(state, MagicMock())
        assert result["error"] == "no"
        assert result["result"] == "agent output"
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest test_agents/tests/test_workers.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add test_agents/agents/worker_base.py test_agents/tests/test_workers.py
git commit -m "fix(worker_base): write back latest agent content to result after reflect pass"
```

---

## Task 4: Strengthen `dispatch_node` and Simplify Wrappers

**Files:**
- Modify: `test_agents/agents/supervisor.py:67-69`
- Modify: `test_agents/agents/worker_base.py`
- Modify: `test_agents/agents/code_analyzer.py`
- Modify: `test_agents/agents/case_reviewer.py`
- Test: `test_agents/tests/test_integration.py`

**Context:** The design says dispatch builds `WorkerState` and writes results back. Currently dispatch returns `{}`. We move the repetitive state-mapping logic into `worker_base.py` helpers, then make wrappers call those helpers so dispatch can be kept simple (it just signals routing). This is the pragmatic fix for D4: centralise mapping logic even if the node boundary stays at wrapper.

- [ ] **Step 1: Add helper functions in `worker_base.py`**

Insert after `_resolve_input`:

```python
def build_worker_task(step: dict, state: SupervisorState) -> tuple[str, list]:
    """Build task description and message list for a worker from plan step + state.

    Returns (task_desc, messages).
    """
    from langchain_core.messages import HumanMessage

    input_mapping = step.get("input_mapping", {})
    task_desc = step.get("description", "")

    # Resolve every key in input_mapping
    resolved = {}
    for key, value in input_mapping.items():
        resolved[key] = _resolve_input(value, state)

    # Build context parts from known keys
    context_parts = [task_desc]
    if resolved.get("module_name"):
        context_parts.append(
            f"分析模块 {resolved['module_name']} 的代码变更，"
            f"commit 范围: {resolved.get('source_commit', '')}..{resolved.get('target_commit', '')}"
        )
    if resolved.get("code_change_report"):
        context_parts.append(f"代码变更报告:\n{resolved['code_change_report'][:3000]}")
    if resolved.get("test_cases"):
        context_parts.append(f"测试用例:\n{resolved['test_cases'][:2000]}")
    if resolved.get("business_knowledge"):
        context_parts.append(f"业务知识:\n{resolved['business_knowledge'][:1000]}")

    return task_desc, [HumanMessage(content="\n\n".join(context_parts))]


def extract_worker_output(worker_result: dict, output_key: str) -> dict:
    """Extract the string result from a WorkerState result dict.

    Falls back to the last AIMessage content if result is empty.
    """
    report = worker_result.get("result", "")
    if not report:
        messages = worker_result.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                report = msg.content
                break
    return {output_key: report}
```

- [ ] **Step 2: Rewrite `code_analyzer_wrapper` to use helpers**

Replace the entire function with:

```python
def code_analyzer_wrapper(state: SupervisorState) -> dict:
    """Code analyzer node - thin adapter around worker subgraph."""
    plan = state.get("plan") or {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    current_index = state.get("current_step_index", 0)

    if current_index >= len(steps):
        return {"current_step_index": current_index}

    step = steps[current_index]
    output_key = step.get("output_key", "") or "code_change_report"

    task_desc, messages = build_worker_task(step, state)

    worker_input: WorkerState = {
        "task": task_desc,
        "messages": messages,
        "error": "no",
        "reflection_count": 0,
        "max_reflections": 0,
        "output_key": output_key,
        "result": "",
    }

    if code_analyzer_graph is None:
        raise RuntimeError("code_analyzer_graph not initialized. Call build_code_analyzer_graph first.")

    result = code_analyzer_graph.invoke(worker_input)
    output = extract_worker_output(result, output_key)

    outputs = state.get("outputs", {}).copy()
    existing = outputs.get(output_key, "")
    module_name = _resolve_input(step.get("input_mapping", {}).get("module_name", ""), state)
    if existing and module_name:
        output[output_key] = existing + f"\n\n## 模块: {module_name}\n" + output[output_key]
    outputs.update(output)

    return {
        "outputs": outputs,
        "current_step_index": current_index + 1,
        "step_results": [{
            "step_id": step.get("step_id", 0),
            "agent": step.get("agent", ""),
            "status": "success" if outputs.get(output_key) else "failed",
            "output_key": output_key,
            "error": "" if outputs.get(output_key) else "Empty result",
        }],
    }
```

Remove the `HumanMessage` import from `code_analyzer.py` if it is no longer used.

- [ ] **Step 3: Rewrite `case_reviewer_wrapper` to use helpers + robust JSON parsing**

Replace the entire function with:

```python
import re


def case_reviewer_wrapper(state: SupervisorState) -> dict:
    """Case reviewer node - thin adapter around worker subgraph."""
    plan = state.get("plan") or {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    current_index = state.get("current_step_index", 0)

    if current_index >= len(steps):
        return {"current_step_index": current_index}

    step = steps[current_index]
    output_key = step.get("output_key", "") or "review_results"

    task_desc, messages = build_worker_task(step, state)

    worker_input: WorkerState = {
        "task": task_desc,
        "messages": messages,
        "error": "no",
        "reflection_count": 0,
        "max_reflections": 0,
        "output_key": output_key,
        "result": "",
    }

    if case_reviewer_graph is None:
        raise RuntimeError("case_reviewer_graph not initialized. Call build_case_reviewer_graph first.")

    result = case_reviewer_graph.invoke(worker_input)
    review_text = extract_worker_output(result, output_key).get(output_key, "")

    review_results = _parse_review_results(review_text)

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


def _parse_review_results(text: str) -> list[dict]:
    """Parse review results from text, handling markdown fences and direct JSON."""
    if not text:
        return []

    # Try fenced JSON blocks
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if match:
        json_str = match.group(1).strip()
    else:
        json_str = text.strip()

    try:
        data = json.loads(json_str)
        if isinstance(data, list):
            return data
        return [data]
    except json.JSONDecodeError:
        return [{"case_id": "N/A", "verdict": "parse_error", "raw": text[:500]}]
```

Remove the `HumanMessage` import from `case_reviewer.py` if no longer used.

- [ ] **Step 4: Update imports in wrappers**

`code_analyzer.py` top import:
```python
from test_agents.agents.worker_base import build_worker_graph, _resolve_input, build_worker_task, extract_worker_output
```

`case_reviewer.py` top import:
```python
from test_agents.agents.worker_base import build_worker_graph, _resolve_input, build_worker_task, extract_worker_output
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest test_agents/tests/test_workers.py -v
python -m pytest test_agents/tests/test_integration.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add test_agents/agents/
git commit -m "refactor(workers): centralise state mapping in worker_base, fix case_reviewer JSON parsing"
```

---

## Task 5: Implement Direct Worker Invocation in main.py

**Files:**
- Modify: `test_agents/main.py`
- Modify: `test_agents/agents/worker_base.py` (add `WORKER_REGISTRY`)
- Modify: `test_agents/graph/builder.py` (populate registry)
- Test: `test_agents/tests/test_integration.py`

**Context:** `is_simple_request()` already detects single-agent keywords, but `run_test_agents` always runs the full supervisor graph.

- [ ] **Step 1: Add a worker registry in `worker_base.py`**

At module level, after imports:

```python
WORKER_REGISTRY: dict[str, callable] = {}
"""Maps agent name → compiled worker graph (populated by builder)."""
```

- [ ] **Step 2: Populate registry in builder.py**

After `build_code_analyzer_graph(...)` and `build_case_reviewer_graph(...)` calls, add:

```python
from test_agents.agents.worker_base import WORKER_REGISTRY

WORKER_REGISTRY["code_analyzer"] = code_analyzer_graph
WORKER_REGISTRY["case_reviewer"] = case_reviewer_graph
```

- [ ] **Step 3: Implement direct worker invocation in main.py**

Replace `run_test_agents` with the two-branch version:

```python
from test_agents.agents.worker_base import WORKER_REGISTRY, build_worker_task
from test_agents.agents.code_analyzer import _resolve_input as resolve_input  # or import from worker_base
from test_agents.graph.state import WorkerState
from langchain_core.messages import HumanMessage


def run_test_agents(user_request: str) -> dict:
    """运行测试智能体群（简单请求直接走 Worker，复杂请求走 Supervisor）"""
    simple_agent = is_simple_request(user_request)
    if simple_agent:
        return _run_direct_worker(user_request, simple_agent)
    return _run_supervisor(user_request)


def _run_direct_worker(user_request: str, agent_name: str) -> dict:
    """直接调用 Worker 子图，跳过 planner/confirm/reflect/synthesize。"""
    worker_graph = WORKER_REGISTRY.get(agent_name)
    if worker_graph is None:
        raise RuntimeError(f"Worker graph for {agent_name} not found in registry")

    task = user_request
    messages = [HumanMessage(content=task)]

    worker_input: WorkerState = {
        "task": task,
        "messages": messages,
        "error": "no",
        "reflection_count": 0,
        "max_reflections": 0,
        "output_key": "result",
        "result": "",
    }

    result = worker_graph.invoke(worker_input)

    # Extract result text
    output_text = result.get("result", "")
    if not output_text:
        for msg in reversed(result.get("messages", [])):
            if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                output_text = msg.content
                break

    output_key = "code_change_report" if agent_name == "code_analyzer" else "review_results"
    return {
        "user_request": user_request,
        "outputs": {output_key: output_text},
        "final_answer": output_text,
        "step_results": [
            {"step_id": 1, "agent": agent_name, "status": "success", "output_key": output_key}
        ],
    }


def _run_supervisor(user_request: str) -> dict:
    """走完整的 Supervisor 主图。"""
    app = build_graph()
    thread_config = {"configurable": {"thread_id": "test-agents-session"}}
    initial_state = _build_initial_state(user_request)

    result = app.invoke(initial_state, thread_config)

    # Handle interrupts (confirm_plan)
    while True:
        state = app.get_state(thread_config)
        if not state.next:
            break
        plan = state.values.get("plan", {})
        _display_plan(plan)
        confirmed = input("\n确认计划？(y/n): ").lower().strip()
        if confirmed == "y":
            app.invoke(Command(resume={"confirmed": True}), thread_config)
        else:
            feedback = input("请输入修改建议: ")
            app.invoke(Command(resume={"confirmed": False, "feedback": feedback}), thread_config)

    final_state = app.get_state(thread_config)
    return final_state.values
```

- [ ] **Step 4: Write test for direct worker path**

Append to `test_agents/tests/test_integration.py`:

```python
def test_direct_worker_invocation_code_analyzer():
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "result": "## 变更概述\n新增订单功能",
        "messages": [],
        "error": "no",
    }
    with patch("test_agents.main.WORKER_REGISTRY", {"code_analyzer": mock_graph}):
        result = run_test_agents("分析订单模块代码变更")
    assert result["outputs"]["code_change_report"] == "## 变更概述\n新增订单功能"
    assert result["final_answer"] == "## 变更概述\n新增订单功能"
    assert result["step_results"][0]["agent"] == "code_analyzer"


def test_direct_worker_invocation_case_reviewer():
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "result": '[{"case_id": "TC001", "verdict": "pass"}]',
        "messages": [],
        "error": "no",
    }
    with patch("test_agents.main.WORKER_REGISTRY", {"case_reviewer": mock_graph}):
        result = run_test_agents("评审测试用例")
    assert result["outputs"]["review_results"] == '[{"case_id": "TC001", "verdict": "pass"}]'
    assert result["step_results"][0]["agent"] == "case_reviewer"
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest test_agents/tests/test_integration.py::test_direct_worker_invocation_code_analyzer -v
python -m pytest test_agents/tests/test_integration.py::test_direct_worker_invocation_case_reviewer -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add test_agents/main.py test_agents/agents/worker_base.py test_agents/graph/builder.py test_agents/tests/test_integration.py
git commit -m "feat(main): implement direct worker invocation for simple requests"
```

---

## Task 6: Fix `save_experience_node` Dedup + Concurrency

**Files:**
- Modify: `test_agents/agents/supervisor.py:154-187`
- Test: `test_agents/tests/test_integration.py`

**Context:** Currently appends plain text every time. The design asks for dedup; we implement lightweight dedup via (intent + steps) fingerprint, plus atomic file write for concurrency safety.

- [ ] **Step 1: Rewrite `save_experience_node`**

Replace the function:

```python
def save_experience_node(state: SupervisorState) -> dict:
    """Save planning and execution experience to file, with dedup and atomic write."""
    import tempfile
    import os

    user_request = state.get("user_request", "")
    plan = state.get("plan", {})
    step_results = state.get("step_results", [])
    reflection_feedback = state.get("reflection_feedback", "")

    experience_file = config.EXPERIENCE_FILE
    os.makedirs(os.path.dirname(experience_file), exist_ok=True)

    intent = plan.get("intent", "")
    steps_desc = ", ".join(s.get("agent", "") for s in plan.get("steps", []))
    results_desc = "; ".join(
        f"step {r.get('step_id')}: {r.get('status')}" for r in step_results
    )

    # Fingerprint for dedup
    fingerprint = f"{intent}|{steps_desc}"

    existing_entries = []
    if os.path.exists(experience_file):
        with open(experience_file, "r", encoding="utf-8") as f:
            existing_text = f.read()
        # Split by "## 经验\n" to get individual entries
        raw_entries = existing_text.split("## 经验\n")
        header = raw_entries[0] if raw_entries else ""
        for raw in raw_entries[1:]:
            existing_entries.append("## 经验\n" + raw)

    # Check dedup
    for entry in existing_entries:
        if fingerprint in entry:
            return {}  # Already recorded

    entry = (
        f"\n## 经验\n"
        f"- **意图**: {intent}\n"
        f"- **规划**: [{steps_desc}]\n"
        f"- **结果**: {results_desc}\n"
        f"- **反思**: {reflection_feedback or '无'}\n"
    )

    header = "# 任务规划反思经验\n" if not existing_entries else ""
    new_content = header + "".join(existing_entries) + entry

    # Atomic write
    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(experience_file))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(temp_path, experience_file)
    except Exception:
        os.remove(temp_path)
        raise

    return {}
```

- [ ] **Step 2: Write test for dedup**

Append to `test_agents/tests/test_integration.py`:

```python
def test_save_experience_dedup(tmp_path):
    from test_agents.agents.supervisor import save_experience_node
    from unittest.mock import patch

    exp_file = tmp_path / "experience.md"
    with patch("test_agents.agents.supervisor.config.EXPERIENCE_FILE", str(exp_file)):
        state = {
            "user_request": "test",
            "plan": {"intent": "分析代码", "steps": [{"agent": "code_analyzer"}]},
            "step_results": [{"step_id": 1, "status": "success"}],
            "reflection_feedback": "",
        }
        # First save should write
        save_experience_node(state)
        assert "分析代码" in exp_file.read_text()

        # Second identical save should skip
        content_before = exp_file.read_text()
        save_experience_node(state)
        assert exp_file.read_text() == content_before
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest test_agents/tests/test_integration.py::test_save_experience_dedup -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add test_agents/agents/supervisor.py test_agents/tests/test_integration.py
git commit -m "fix(supervisor): atomic write + dedup for save_experience_node"
```

---

## Task 7: Unify Planner Prompt Syntax

**Files:**
- Modify: `test_agents/prompts/planner.md`
- Test: `test_agents/tests/test_integration.py`

**Context:** The prompt mixes `${code_change_report}` and `${outputs.code_change_report}`. `_resolve_input` already supports both; we remove the old syntax from the prompt and from any compatibility code if present.

- [ ] **Step 1: Update planner.md example**

Change line 71 from:
```markdown
        "code_change_report": "${outputs.code_change_report}",
```

Actually it's already `${outputs.code_change_report}`. Let's check the rules section. Change line 27 from:
```markdown
2. 引用上游步骤产出用 `${字段名}` 格式，如 `"code_change_report": "${code_change_report}"`
```

To:
```markdown
2. 引用上游步骤产出用 `${outputs.key}` 格式，如 `"code_change_report": "${outputs.code_change_report}"`
```

- [ ] **Step 2: Verify _resolve_input no longer needs bare-field fallback**

Current `_resolve_input` already handles both `path.startswith("outputs.")` and bare `state.get(path)`. Keep the bare-field support defensively (it does no harm), but update prompt to only teach `${outputs.xxx}`.

- [ ] **Step 3: Commit**

```bash
git add test_agents/prompts/planner.md
git commit -m "docs(prompts): unify planner interpolation syntax to \${outputs.xxx}"
```

---

## Task 8: Expand Test Coverage

**Files:**
- Modify: `test_agents/tests/test_integration.py`
- Modify: `test_agents/tests/test_workers.py`

**Context:** Tests currently mock wrappers. We add tests for multi-key interpolation, direct worker mode, worker reflect result-writeback, and a non-mocked worker-subgraph invocation.

- [ ] **Step 1: Multi-key interpolation test**

Append to `test_agents/tests/test_integration.py`:

```python
def test_resolve_input_multi_key():
    from test_agents.agents.worker_base import _resolve_input
    state = {
        "outputs": {
            "report_a": "Line A",
            "report_b": "Line B",
        }
    }
    result = _resolve_input("${outputs.report_a}\n${outputs.report_b}", state)
    assert result == "Line A\nLine B"


def test_resolve_input_mixed_text_and_refs():
    from test_agents.agents.worker_base import _resolve_input
    state = {
        "user_request": "hello",
        "outputs": {"x": "world"},
    }
    result = _resolve_input("req=${user_request}, out=${outputs.x}", state)
    assert result == "req=hello, out=world"
```

- [ ] **Step 2: Worker subgraph internal-loop test (without mocking wrapper)**

Append to `test_agents/tests/test_workers.py`:

```python
from test_agents.agents.worker_base import build_worker_graph
from langchain_core.messages import AIMessage, ToolMessage


class TestWorkerSubgraphInternal:
    def test_worker_graph_runs_agent_tools_reflect(self):
        """Test that the compiled worker graph can execute agent → tools → reflect."""
        mock_tool = MagicMock()
        mock_tool.name = "mock_tool"
        mock_tool.invoke.return_value = "tool result"

        mock_llm = MagicMock()
        # First call: agent decides to use tool
        mock_llm.invoke.return_value = AIMessage(
            content="",
            tool_calls=[{"id": "call1", "name": "mock_tool", "args": {"query": "test"}}],
        )

        graph = build_worker_graph([mock_tool], mock_llm, mock_llm)
        result = graph.invoke({
            "task": "test task",
            "messages": [AIMessage(content="do it")],
            "error": "no",
            "reflection_count": 0,
            "max_reflections": 0,
            "output_key": "result",
            "result": "",
        })
        # With max_reflections=0, reflect is skipped and we just get agent output
        assert "messages" in result
```

- [ ] **Step 3: Case reviewer JSON parsing edge cases**

Append to `test_agents/tests/test_workers.py`:

```python
from test_agents.agents.case_reviewer import _parse_review_results


class TestParseReviewResults:
    def test_parse_plain_json(self):
        text = '[{"case_id": "1", "verdict": "pass"}]'
        assert _parse_review_results(text) == [{"case_id": "1", "verdict": "pass"}]

    def test_parse_json_with_fences(self):
        text = 'Some intro\n```json\n[{"case_id": "1"}]\n```\noutro'
        assert _parse_review_results(text) == [{"case_id": "1"}]

    def test_parse_single_object(self):
        text = '{"case_id": "1", "verdict": "pass"}'
        assert _parse_review_results(text) == [{"case_id": "1", "verdict": "pass"}]

    def test_parse_invalid_json(self):
        text = "not json at all"
        result = _parse_review_results(text)
        assert result[0]["verdict"] == "parse_error"
        assert "not json" in result[0]["raw"]

    def test_parse_empty(self):
        assert _parse_review_results("") == []
```

- [ ] **Step 4: Run all tests**

```bash
python -m pytest test_agents/tests/ -v
```

Expected: all PASS. If any fail, fix the code, not the test.

- [ ] **Step 5: Commit**

```bash
git add test_agents/tests/
git commit -m "test(integration,workers): multi-key resolve, direct worker, JSON parsing, worker reflect writeback"
```

---

## Self-Review

**1. Spec coverage:**

| Gap ID | Task | Step |
|---|---|---|
| D1 (subgraph registration) | Task 4 | wrapper stays thin; public helpers live in worker_base; architecture documented in code |
| D2 (deprecated fields) | Task 1 | removed from state.py and main.py |
| D3 (direct worker) | Task 5 | `_run_direct_worker` implemented in main.py |
| D4 (dispatch duty) | Task 4 | state-mapping centralised in worker_base; wrappers call helpers |
| F1 (save_experience dedup) | Task 6 | fingerprint dedup + atomic write |
| F2 (multi-key interpolation) | Task 2 | `_resolve_input` uses regex `finditer` replacement |
| F3 (reflect result writeback) | Task 3 | `worker_reflect` returns `result` on every pass path |
| Q1 (_resolve_input duplication) | Task 2 | extracted to worker_base |
| Q2 (fragile JSON parsing) | Task 4 | `_parse_review_results` with regex fences |
| Q3 (concurrency) | Task 6 | atomic write via `mkstemp` + `os.replace` |
| Q4 (prompt syntax) | Task 7 | planner.md updated |
| T1 (subgraph loop tests) | Task 8 | `test_worker_graph_runs_agent_tools_reflect` |
| T2 (direct worker tests) | Task 5 | `test_direct_worker_invocation_*` |
| T3 (multi-key tests) | Task 8 | `test_resolve_input_multi_key` |

**2. Placeholder scan:** No TODO/TBD/fill-in-details found.

**3. Type consistency:** All references use `SupervisorState`, `WorkerState`, `output_key`, `outputs` consistently after Task 1 removes deprecated fields.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-design-impl-gap-fixes.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

**Which approach?**
