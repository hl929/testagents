"""Supervisor nodes for Plan-and-Solve + Reflection architecture"""

import json
import os
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt
from langchain_openai import ChatOpenAI

from test_agents.config import config
from test_agents.graph.state import SupervisorState, ExecutionPlan
from test_agents.prompts.loader import load_prompt
from test_agents.tools.base import ToolRegistry


def get_llm():
    """Get llm response"""
    kwargs = {"model": config.LLM_MODEL, "api_key": config.LLM_API_KEY}
    if config.LLM_BASE_URL:
        kwargs["base_url"] = config.LLM_BASE_URL
    return ChatOpenAI(**kwargs)


def planner_node(state: SupervisorState) -> dict:
    """Parse user_request and generate ExecutionPlan"""
    llm = get_llm()
    user_request = state.get("user_request", "")
    tools_info = ToolRegistry.render_all()
    prompt = load_prompt("planner", user_request=user_request, tools_info=tools_info)

    structured_llm = llm.with_structured_output(ExecutionPlan)
    plan = structured_llm.invoke([HumanMessage(content=prompt)])

    if isinstance(plan, ExecutionPlan):
        plan_dict = plan.model_dump()
    elif isinstance(plan, dict):
        plan_dict = plan
    else:
        plan_dict = {"intent": "解析失败", "steps": [], "confirmed": False}

    return {
        "plan": plan_dict,
        "plan_iterations": state.get("plan_iterations", 0) + 1,
    }


def confirm_plan_node(state: SupervisorState) -> dict:
    """Interrupt for user plan confirmation"""
    plan = state.get("plan", {})
    response = interrupt({
        "type": "confirm_plan",
        "plan": plan,
    })

    if response.get("confirmed", False):
        plan["confirmed"] = True
        return {"plan": plan}
    else:
        feedback = response.get("feedback", "")
        return {
            "confirm_retry_count": state.get("confirm_retry_count", 0) + 1,
            "messages": [HumanMessage(content=f"用户拒绝了计划，反馈：{feedback}")],
        }


def dispatch_node(state: SupervisorState) -> dict:
    """Dispatch hub - routes to workers or reflect based on current_step_index"""
    return {}


def reflect_node(state: SupervisorState) -> dict:
    """Supervisor reflect - evaluate overall results"""
    llm = get_llm()
    user_request = state.get("user_request", "")
    plan = state.get("plan", {})
    step_results = state.get("step_results", [])

    plan_summary = json.dumps(plan.get("steps", []), ensure_ascii=False)
    step_results_summary = json.dumps(step_results, ensure_ascii=False)

    prompt = load_prompt(
        "supervisor_reflect",
        user_request=user_request,
        plan_summary=plan_summary,
        step_results_summary=step_results_summary,
    )

    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        assessment = json.loads(content)

        if assessment.get("assessment") == "REPLAN":
            return {
                "needs_replan": True,
                "plan_iterations": state.get("plan_iterations", 0) + 1,
                "reflection_feedback": assessment.get("feedback", ""),
            }
        else:
            return {
                "needs_replan": False,
                "reflection_feedback": assessment.get("feedback", ""),
            }
    except (json.JSONDecodeError, AttributeError, IndexError):
        return {"needs_replan": False, "reflection_feedback": "反思评估解析失败，默认完成"}


def synthesize_node(state: SupervisorState) -> dict:
    """Synthesize all step results into final answer"""
    llm = get_llm()
    user_request = state.get("user_request", "")
    plan = state.get("plan", {})
    step_results = state.get("step_results", [])

    plan_summary = json.dumps(plan.get("steps", []), ensure_ascii=False)
    step_results_summary = json.dumps(step_results, ensure_ascii=False)

    prompt = load_prompt(
        "synthesize",
        user_request=user_request,
        plan_summary=plan_summary,
        step_results_summary=step_results_summary,
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"final_answer": response.content}


def save_experience_node(state: SupervisorState) -> dict:
    """Save planning and execution experience to file"""
    user_request = state.get("user_request", "")
    plan = state.get("plan", {})
    step_results = state.get("step_results", [])
    reflection_feedback = state.get("reflection_feedback", "")

    experience_file = config.EXPERIENCE_FILE
    os.makedirs(os.path.dirname(experience_file), exist_ok=True)

    existing = ""
    if os.path.exists(experience_file):
        with open(experience_file, "r", encoding="utf-8") as f:
            existing = f.read()

    intent = plan.get("intent", "")
    steps_desc = ", ".join(s.get("agent", "") for s in plan.get("steps", []))
    results_desc = "; ".join(
        f"step {r.get('step_id')}: {r.get('status')}" for r in step_results
    )

    entry = (
        f"\n## 经验\n"
        f"- **意图**: {intent}\n"
        f"- **规划**: [{steps_desc}]\n"
        f"- **结果**: {results_desc}\n"
        f"- **反思**: {reflection_feedback or '无'}\n"
    )

    header = "# 任务规划反思经验\n" if not existing else ""
    with open(experience_file, "a", encoding="utf-8") as f:
        f.write(header + entry)

    return {}


# === Route Functions ===

def route_from_confirm(state: SupervisorState) -> Literal["dispatch", "planner", "end"]:
    """Route after confirm_plan: confirmed→dispatch, rejected→planner, over limit→end"""
    plan = state.get("plan") or {}
    if plan.get("confirmed", False):
        return "dispatch"
    if state.get("confirm_retry_count", 0) >= state.get("max_confirm_retries", 3):
        return "end"
    return "planner"


def route_from_dispatch(state: SupervisorState) -> Literal["code_analyzer", "case_reviewer", "reflect"]:
    """Route after dispatch: more steps→worker, all done→reflect"""
    plan = state.get("plan") or {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    current_index = state.get("current_step_index", 0)

    if current_index >= len(steps):
        return "reflect"

    agent = steps[current_index].get("agent", "")
    if agent == "code_analyzer":
        return "code_analyzer"
    elif agent == "case_reviewer":
        return "case_reviewer"
    return "reflect"


def route_from_reflect(state: SupervisorState) -> Literal["planner", "synthesize"]:
    """Route after reflect: replan→planner, complete→synthesize"""
    if state.get("needs_replan") and state.get("plan_iterations", 0) < state.get("max_plan_iterations", 1):
        return "planner"
    return "synthesize"
