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
