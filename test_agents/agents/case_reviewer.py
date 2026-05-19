"""Case reviewer worker - ReAct subgraph with ClaudeCliTool + TestCaseParserTool + BusinessKnowledgeTool"""

import json
import re
from langchain_core.messages import HumanMessage

from test_agents.agents.worker_base import build_worker_graph, _resolve_input, build_worker_task, extract_worker_output
from test_agents.graph.state import SupervisorState, WorkerState
from test_agents.tools.base import ToolRegistry


_case_reviewer_tools = ToolRegistry.get_tools_by_names(["claude_cli", "parse_test_cases", "query_business_knowledge"])
case_reviewer_graph = None


def build_case_reviewer_graph(llm, llm_with_tools):
    """Build and cache the case reviewer subgraph"""
    global case_reviewer_graph
    case_reviewer_graph = build_worker_graph(_case_reviewer_tools, llm, llm_with_tools)
    return case_reviewer_graph




def _parse_review_results(text: str) -> list[dict]:
    """Parse review results from text, handling markdown fences and direct JSON."""
    if not text:
        return []
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
        "task": task_desc, "messages": messages,
        "error": "no", "reflection_count": 0, "max_reflections": 0,
        "output_key": output_key, "result": "",
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
            "step_id": step.get("step_id", 0), "agent": step.get("agent", ""),
            "status": "success" if review_results else "failed",
            "output_key": output_key,
            "error": "" if review_results else "Empty result",
        }],
    }
