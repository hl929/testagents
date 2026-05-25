"""Case reviewer worker - ReAct subgraph with ClaudeCliTool + TestCaseParserTool + BusinessKnowledgeTool"""

import json
import re

from test_agents.agents.worker_base import build_worker_graph, aggregate_worker_result
from test_agents.graph.state import SupervisorState
from test_agents.prompts.loader import load_prompt
from test_agents.tools.base import ToolRegistry


_case_reviewer_tools = ToolRegistry.get_tools_by_names(["claude_cli", "parse_test_cases", "query_business_knowledge"])
case_reviewer_graph = None


def build_case_reviewer_graph(llm, llm_with_tools):
    """Build and cache the case reviewer subgraph"""
    global case_reviewer_graph
    case_reviewer_graph = build_worker_graph(
        _case_reviewer_tools,
        llm,
        llm_with_tools,
        system_prompt=load_prompt("case_reviewer"),
    )
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
    worker_input = state.get("worker_input")
    if not worker_input:
        return {}
    if case_reviewer_graph is None:
        raise RuntimeError("case_reviewer_graph not initialized. Call build_case_reviewer_graph first.")
    result = case_reviewer_graph.invoke(worker_input)
    return aggregate_worker_result(
        state, result, worker_input["output_key"], "case_reviewer",
        post_processor=_parse_review_results
    )
