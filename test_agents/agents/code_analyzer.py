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
            if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
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
