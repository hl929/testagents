"""Code analyzer worker - ReAct subgraph with ClaudeCliTool"""

import json
from langchain_core.messages import HumanMessage

from test_agents.agents.worker_base import build_worker_graph, _resolve_input, build_worker_task, extract_worker_output
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
        "task": task_desc, "messages": messages,
        "error": "no", "reflection_count": 0, "max_reflections": 0,
        "output_key": output_key, "result": "",
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
            "step_id": step.get("step_id", 0), "agent": step.get("agent", ""),
            "status": "success" if outputs.get(output_key) else "failed",
            "output_key": output_key,
            "error": "" if outputs.get(output_key) else "Empty result",
        }],
    }
