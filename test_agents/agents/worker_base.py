"""Worker subgraph factory - ReAct + Reflection pattern"""

import json
import re
from typing import Literal

WORKER_REGISTRY: dict[str, any] = {}
"""Maps agent name → compiled worker graph (populated by builder)."""

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


def build_worker_task(step: dict, state: SupervisorState) -> tuple[str, list]:
    """Build task description and message list for a worker from plan step + state.
    Returns (task_desc, messages).
    """
    input_mapping = step.get("input_mapping", {})
    task_desc = step.get("description", "")
    resolved = {}
    for key, value in input_mapping.items():
        resolved[key] = _resolve_input(value, state)
    context_parts = [task_desc]
    if resolved.get("module_name"):
        context_parts.append(
            f"分析模块 {resolved['module_name']} 的代码变更，"
            f"commit 范围: {resolved.get('source_commit', '')}..{resolved.get('target_commit', '')}"
        )
    if resolved.get("code_change_report"):
        context_parts.append(f"代码变更报告:\n{resolved['code_change_report'][:3000]}")
    if resolved.get("test_cases"):
        context_parts.append(f"测试用例:\n{resolved['test_cases'][:2000]}")
    if resolved.get("business_knowledge"):
        context_parts.append(f"业务知识:\n{resolved['business_knowledge'][:1000]}")
    if resolved.get("time_range"):
        context_parts.append(f"时间范围: {resolved['time_range']}")
    if resolved.get("metrics"):
        context_parts.append(f"关注指标: {resolved['metrics']}")
    if resolved.get("file_path"):
        context_parts.append(f"测试数据文件: {resolved['file_path']}")
    if resolved.get("business_line"):
        context_parts.append(f"业务线: {resolved['business_line']}")
    if resolved.get("template_name"):
        context_parts.append(f"报告模板: {resolved['template_name']}")
    return task_desc, [HumanMessage(content="\n\n".join(context_parts))]


def extract_worker_output(worker_result: dict, output_key: str) -> dict:
    """Extract the string result from a WorkerState result dict.
    Falls back to the last AIMessage content if result is empty.
    """
    report = worker_result.get("result", "")
    if not report:
        messages = worker_result.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                report = msg.content
                break
    return {output_key: report}


def aggregate_worker_result(
    state: SupervisorState,
    worker_result: dict,
    output_key: str,
    agent_name: str,
    post_processor=None,
) -> dict:
    """Generic worker result aggregation: extract result, optionally post-process,
    update outputs with dedup, and generate step_result.
    """
    output_value = extract_worker_output(worker_result, output_key).get(output_key, "")

    if post_processor:
        output_value = post_processor(output_value)

    outputs = state.get("outputs", {}).copy()
    existing = outputs.get(output_key, "")

    plan = state.get("plan") or {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    current_index = state.get("current_step_index", 0)
    step = steps[current_index] if current_index < len(steps) else {}
    module_name = step.get("input_mapping", {}).get("module_name", "")
    if module_name:
        section = f"## 模块: {module_name}\n{output_value}"
        output_value = f"{existing}\n\n{section}" if existing else section

    outputs[output_key] = output_value

    return {
        "outputs": outputs,
        "current_step_index": current_index + 1,
        "step_results": [{
            "step_id": step.get("step_id", 0),
            "agent": agent_name,
            "status": "success" if output_value else "failed",
            "output_key": output_key,
            "error": "" if output_value else "Empty result",
        }],
    }


def agent_node(state: WorkerState, llm_with_tools, system_prompt: str | None = None) -> dict:
    """Worker agent node - LLM with tool binding"""
    messages = state.get("messages", [])
    invocation_messages = [SystemMessage(content=system_prompt), *messages] if system_prompt else messages
    response = llm_with_tools.invoke(invocation_messages)
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


def build_worker_graph(tools: list, llm, llm_with_tools, system_prompt: str | None = None):
    """Build a ReAct + Reflection Worker subgraph"""
    def agent_node_bound(state: WorkerState) -> dict:
        return agent_node(state, llm_with_tools, system_prompt)

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
