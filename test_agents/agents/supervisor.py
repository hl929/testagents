"""Supervisor nodes for Plan-and-Solve + Reflection architecture"""

import json
import os
import tempfile
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


def _strip_markdown_json(text: str) -> str:
    """剥离 LLM 返回的 markdown 代码围栏"""
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text.strip()


def intent_classifier_node(state: SupervisorState) -> dict:
    """Classify user request intent before entering planner."""
    llm = get_llm()
    user_request = state.get("user_request", "")
    prompt = load_prompt("intent_classifier", user_request=user_request)

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = _strip_markdown_json(response.content)
        assessment = json.loads(content)
        classification = assessment.get("classification", "ambiguous")
        reason = assessment.get("reason", "")
        if classification not in ("relevant", "ambiguous", "irrelevant"):
            classification = "ambiguous"
    except (json.JSONDecodeError, Exception):
        classification = "ambiguous"
        reason = "意图分类解析失败，默认按模糊请求处理"

    return {
        "intent_classification": classification,
        "intent_reason": reason,
    }


def reply_node(state: SupervisorState) -> dict:
    """Generate friendly reply for irrelevant or ambiguous requests."""
    llm = get_llm()
    user_request = state.get("user_request", "")
    classification = state.get("intent_classification", "ambiguous")
    reason = state.get("intent_reason", "")

    prompt = load_prompt(
        "reply",
        user_request=user_request,
        classification=classification,
        reason=reason,
    )

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return {"final_answer": response.content}
    except Exception:
        # 降级到硬编码回复模板，确保流程不中断
        if classification == "irrelevant":
            fallback = (
                "您好！我是 Test Agents，专门用于分析代码变更和评审测试用例。"
                "如果您有代码分析需求，请告诉我模块名和 commit 范围。"
            )
        else:
            fallback = (
                "好的，我可以帮您评审测试用例。请补充以下信息："
                "1）需要分析的模块名称；2）代码变更的 commit 范围（如有）；"
                "3）需要评审的具体测试用例内容。"
            )
        return {"final_answer": fallback}


def planner_node(state: SupervisorState) -> dict:
    """Parse user_request and generate ExecutionPlan"""
    llm = get_llm()
    user_request = state.get("user_request", "")
    tools_info = ToolRegistry.render_all()
    prompt = load_prompt("planner", user_request=user_request, tools_info=tools_info)

    response = llm.invoke([HumanMessage(content=prompt)])
    content = _strip_markdown_json(response.content)

    try:
        plan = ExecutionPlan.model_validate_json(content)
        plan_dict = plan.model_dump()
    except Exception:
        try:
            plan = ExecutionPlan.model_validate(json.loads(content))
            plan_dict = plan.model_dump()
        except Exception:
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
    outputs = state.get("outputs", {})
    plan_iterations = state.get("plan_iterations", 0)
    max_plan_iterations = state.get("max_plan_iterations", 1)

    plan_summary = json.dumps(plan.get("steps", []), ensure_ascii=False)
    step_results_summary = json.dumps(step_results, ensure_ascii=False)

    output_parts = []
    for key, value in outputs.items():
        content = str(value)[:1000] if value else "(空)"
        output_parts.append(f"**{key}**:\n{content}")
    outputs_summary = "\n\n".join(output_parts) if output_parts else "(无输出)"

    prompt = load_prompt(
        "supervisor_reflect",
        user_request=user_request,
        plan_summary=plan_summary,
        step_results_summary=step_results_summary,
        outputs_summary=outputs_summary,
        plan_iterations=plan_iterations,
        max_plan_iterations=max_plan_iterations,
    )

    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        content = _strip_markdown_json(response.content)
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
    outputs = state.get("outputs", {})

    plan_summary = json.dumps(plan.get("steps", []), ensure_ascii=False)
    step_results_summary = json.dumps(step_results, ensure_ascii=False)

    output_summaries = []
    for key, value in outputs.items():
        summary = f"【{key}】\n{str(value)[:3000]}"
        output_summaries.append(summary)

    prompt = load_prompt(
        "synthesize",
        user_request=user_request,
        plan_summary=plan_summary,
        step_results_summary=step_results_summary,
        outputs="\n\n---\n\n".join(output_summaries),
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"final_answer": response.content}


def save_experience_node(state: SupervisorState) -> dict:
    """Save planning and execution experience to file, with dedup and atomic write."""
    user_request = state.get("user_request", "")
    plan = state.get("plan", {})
    step_results = state.get("step_results", [])
    reflection_feedback = state.get("reflection_feedback", "")

    experience_file = config.EXPERIENCE_FILE
    os.makedirs(os.path.dirname(experience_file), exist_ok=True)

    intent = plan.get("intent", "")
    steps_desc = ", ".join(s.get("agent", "") for s in plan.get("steps", []))
    results_desc = "; ".join(
        f"step {r.get('step_id')}: {r.get('status')}" for r in step_results
    )

    # Fingerprint for dedup
    fingerprint = f"{intent}|{steps_desc}"

    existing_entries = []
    if os.path.exists(experience_file):
        with open(experience_file, "r", encoding="utf-8") as f:
            existing_text = f.read()
        raw_entries = existing_text.split("## 经验\n")
        for raw in raw_entries[1:]:
            existing_entries.append("## 经验\n" + raw)

    # Check dedup - 检查意图和步骤描述都包含在条目中
    for entry in existing_entries:
        if intent in entry and steps_desc in entry:
            return {}  # Already recorded

    entry = (
        f"\n## 经验\n"
        f"- **意图**: {intent}\n"
        f"- **规划**: [{steps_desc}]\n"
        f"- **结果**: {results_desc}\n"
        f"- **反思**: {reflection_feedback or '无'}\n"
    )

    header = "# 任务规划反思经验\n" if not existing_entries else ""
    new_content = header + "".join(existing_entries) + entry

    # Atomic write
    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(experience_file))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(temp_path, experience_file)
    except Exception:
        os.remove(temp_path)
        raise

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


def route_from_classifier(state: SupervisorState) -> Literal["planner", "reply"]:
    """Route after intent_classifier: relevant→planner, other→reply"""
    classification = state.get("intent_classification", "")
    if classification == "relevant":
        return "planner"
    return "reply"
