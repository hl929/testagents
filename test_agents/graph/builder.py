"""Graph builder - main graph assembly for Plan-and-Solve + Reflection"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

from test_agents.agents.supervisor import (
    planner_node,
    confirm_plan_node,
    dispatch_node,
    reflect_node,
    synthesize_node,
    save_experience_node,
    route_from_confirm,
    route_from_dispatch,
    route_from_reflect,
    get_llm,
)
from test_agents.agents.code_analyzer import (
    build_code_analyzer_graph,
    code_analyzer_wrapper,
)
from test_agents.agents.case_reviewer import (
    build_case_reviewer_graph,
    case_reviewer_wrapper,
)
from test_agents.agents.worker_base import WORKER_REGISTRY
from test_agents.graph.state import SupervisorState


def build_graph():
    """Build and compile the supervisor graph with worker subgraphs"""
    llm = get_llm()

    code_analyzer_tools = _get_code_analyzer_tools()
    case_reviewer_tools = _get_case_reviewer_tools()

    llm_with_ca_tools = llm.bind_tools(code_analyzer_tools)
    llm_with_cr_tools = llm.bind_tools(case_reviewer_tools)

    code_analyzer_graph = build_code_analyzer_graph(llm, llm_with_ca_tools)
    case_reviewer_graph = build_case_reviewer_graph(llm, llm_with_cr_tools)
    WORKER_REGISTRY["code_analyzer"] = code_analyzer_graph
    WORKER_REGISTRY["case_reviewer"] = case_reviewer_graph

    graph = StateGraph(SupervisorState)

    # Add nodes
    graph.add_node("planner", planner_node)
    graph.add_node("confirm_plan", confirm_plan_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("code_analyzer", code_analyzer_wrapper)
    graph.add_node("case_reviewer", case_reviewer_wrapper)
    graph.add_node("reflect", reflect_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("save_experience", save_experience_node)

    # Fixed edges
    graph.add_edge(START, "planner")
    graph.add_edge("code_analyzer", "dispatch")
    graph.add_edge("case_reviewer", "dispatch")
    graph.add_edge("synthesize", "save_experience")
    graph.add_edge("save_experience", END)

    # Conditional edges
    graph.add_conditional_edges("planner", lambda state: "confirm_plan", {"confirm_plan": "confirm_plan"})

    graph.add_conditional_edges(
        "confirm_plan",
        route_from_confirm,
        {"dispatch": "dispatch", "planner": "planner", "end": END},
    )

    graph.add_conditional_edges(
        "dispatch",
        route_from_dispatch,
        {"code_analyzer": "code_analyzer", "case_reviewer": "case_reviewer", "reflect": "reflect"},
    )

    graph.add_conditional_edges(
        "reflect",
        route_from_reflect,
        {"planner": "planner", "synthesize": "synthesize"},
    )

    memory = InMemorySaver()
    return graph.compile(checkpointer=memory)


def _get_code_analyzer_tools():
    from test_agents.tools.base import ToolRegistry
    return ToolRegistry.get_tools_by_names(["claude_cli"])


def _get_case_reviewer_tools():
    from test_agents.tools.base import ToolRegistry
    return ToolRegistry.get_tools_by_names(["claude_cli", "parse_test_cases", "query_business_knowledge"])
