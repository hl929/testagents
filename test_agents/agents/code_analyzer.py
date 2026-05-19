"""Code analyzer worker - ReAct subgraph with ClaudeCliTool"""

import json
from langchain_core.messages import HumanMessage

from test_agents.agents.worker_base import build_worker_graph, _resolve_input
from test_agents.graph.state import SupervisorState, WorkerState
from test_agents.tools.base import ToolRegistry


_code_analyzer_tools = ToolRegistry.get_tools_by_names(["claude_cli"])
code_analyzer_graph = None


def build_code_analyzer_graph(llm, llm_with_tools):
    """Build and cache the code analyzer subgraph"""
    global code_analyzer_graph
    code_analyzer_graph = build_worker_graph(_code_analyzer_tools, llm, llm_with_tools)
    return code_analyzer_graph




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
