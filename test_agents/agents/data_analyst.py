"""Data analyst worker - ReAct subgraph with QueryDatabaseTool + SchemaDescriptionTool"""

from test_agents.agents.worker_base import build_worker_graph, aggregate_worker_result
from test_agents.graph.state import SupervisorState
from test_agents.prompts.loader import load_prompt
from test_agents.tools.base import ToolRegistry


_data_analyst_tools = ToolRegistry.get_tools_by_names(
    ["query_database", "describe_schema"]
)
data_analyst_graph = None


def build_data_analyst_graph(llm, llm_with_tools):
    """Build and cache the data analyst subgraph"""
    global data_analyst_graph
    data_analyst_graph = build_worker_graph(
        _data_analyst_tools,
        llm,
        llm_with_tools,
        system_prompt=load_prompt("data_analyst"),
    )
    return data_analyst_graph


def data_analyst_wrapper(state: SupervisorState) -> dict:
    """Data analyst node - thin adapter around worker subgraph."""
    worker_input = state.get("worker_input")
    if not worker_input:
        return {}
    if data_analyst_graph is None:
        raise RuntimeError(
            "data_analyst_graph not initialized. Call build_data_analyst_graph first."
        )
    result = data_analyst_graph.invoke(worker_input)
    return aggregate_worker_result(
        state, result, worker_input["output_key"], "data_analyst"
    )
