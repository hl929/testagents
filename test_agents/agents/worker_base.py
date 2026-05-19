"""Worker subgraph factory - ReAct + Reflection pattern"""

import json
import re
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from test_agents.graph.state import WorkerState, SupervisorState
from test_agents.prompts.loader import load_prompt


def _resolve_input(value: str, state: SupervisorState) -> str:
    """Resolve input_mapping value: ${field} → state field, ${outputs.key} → outputs dict, with multi-key interpolation support"""

    def replace_placeholder(match):
        path = match.group(1)

        if path.startswith("outputs."):
            outputs = state.get("outputs", {})
            key = path[8:]
            val = outputs.get(key, "")
        else:
            val = state.get(path, "")

        return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)

    return re.sub(r'\$\{([^}]+)\}', replace_placeholder, value)


def agent_node(state: WorkerState, llm_with_tools) -> dict:
    """Worker agent node - LLM with tool binding"""
    messages = state.get("messages", [])
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def _extract_last_agent_content(state: WorkerState) -> str:
    """Extract the last non-tool AIMessage content from messages."""
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
            return msg.content
    return state.get("result", "")


def worker_reflect(state: WorkerState, llm) -> dict:
    """Worker reflect node - evaluate result quality"""
    max_reflections = state.get("max_reflections", 0)
    if max_reflections == 0:
        return {"error": "no", "result": _extract_last_agent_content(state)}

    reflection_count = state.get("reflection_count", 0)
    if reflection_count >= max_reflections:
        return {"error": "no", "result": _extract_last_agent_content(state)}

    result = state.get("result", "")
    messages = state.get("messages", [])
    if not result and messages:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                result = msg.content
                break

    task = state.get("task", "")
    prompt = load_prompt(
        "worker_reflect",
        task=task,
        result=result[:2000],
        reflection_count=reflection_count,
        max_reflections=max_reflections,
    )
    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        assessment = json.loads(content)
        if assessment.get("quality") == "pass":
            return {"error": "no", "result": _extract_last_agent_content(state)}
        feedback = assessment.get("feedback", "")
        return {
            "error": "yes",
            "reflection_count": reflection_count + 1,
            "messages": [HumanMessage(content=f"质量评估不通过，请重试。反馈：{feedback}")],
        }
    except (json.JSONDecodeError, AttributeError, IndexError):
        return {"error": "no", "result": _extract_last_agent_content(state)}


def worker_route(state: WorkerState) -> Literal["agent", "__end__"]:
    """Route after reflect: retry or end"""
    if state.get("error") == "no":
        return "__end__"
    if state.get("reflection_count", 0) >= state.get("max_reflections", 0):
        return "__end__"
    return "agent"


def build_worker_graph(tools: list, llm, llm_with_tools):
    """Build a ReAct + Reflection Worker subgraph"""
    def agent_node_bound(state: WorkerState) -> dict:
        return agent_node(state, llm_with_tools)

    def worker_reflect_bound(state: WorkerState) -> dict:
        return worker_reflect(state, llm)

    graph = StateGraph(WorkerState)
    graph.add_node("agent", agent_node_bound)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("reflect", worker_reflect_bound)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", "__end__": "reflect"})
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("reflect", worker_route, {"agent": "agent", "__end__": END})

    return graph.compile()
