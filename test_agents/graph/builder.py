"""图编排构建器"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

from test_agents.agents.supervisor import supervisor_node
from test_agents.agents.code_analyzer import code_analyzer_node
from test_agents.agents.case_reviewer import case_reviewer_node
from test_agents.graph.state import TestAgentState


def build_graph():
    """构建并编译测试智能体群图"""
    graph = StateGraph(TestAgentState)

    # 添加节点
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("code_analyzer", code_analyzer_node)
    graph.add_node("case_reviewer", case_reviewer_node)

    # 固定边
    graph.add_edge(START, "supervisor")
    graph.add_edge("code_analyzer", "supervisor")
    graph.add_edge("case_reviewer", "supervisor")

    # 条件边：Supervisor 决策路由
    graph.add_conditional_edges(
        "supervisor",
        lambda state: getattr(state, "next_step", state.model_dump().get("next_step", "end") if hasattr(state, "model_dump") else "end"),
        {
            "analyze": "code_analyzer",
            "review": "case_reviewer",
            "end": END,
        }
    )

    # 编译时传入 checkpointer
    memory = InMemorySaver()
    app = graph.compile(checkpointer=memory)

    return app
