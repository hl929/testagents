"""Code analyzer worker - ReAct subgraph with ClaudeCliTool"""

from test_agents.agents.worker_base import build_worker_graph, aggregate_worker_result
from test_agents.graph.state import SupervisorState
from test_agents.prompts.loader import load_prompt
from test_agents.tools.base import ToolRegistry


_code_analyzer_tools = ToolRegistry.get_tools_by_names(
    ["claude_cli", "read_file", "list_dir", "grep", "glob"]
)
code_analyzer_graph = None


def build_code_analyzer_graph(llm, llm_with_tools):
    """Build and cache the code analyzer subgraph"""
    global code_analyzer_graph
    code_analyzer_graph = build_worker_graph(
        _code_analyzer_tools,
        llm,
        llm_with_tools,
        system_prompt=load_prompt("code_analyzer"),
    )
    return code_analyzer_graph


def code_analyzer_wrapper(state: SupervisorState) -> dict:
    """Code analyzer node - thin adapter around worker subgraph."""
    worker_input = state.get("worker_input")
    if not worker_input:
        return {}
    if code_analyzer_graph is None:
        raise RuntimeError("code_analyzer_graph not initialized. Call build_code_analyzer_graph first.")
    result = code_analyzer_graph.invoke(worker_input)
    return aggregate_worker_result(
        state, result, worker_input["output_key"], "code_analyzer"
    )
