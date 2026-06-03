"""Supervisor nodes for Plan-and-Solve + Reflection architecture"""

import json
import os
import tempfile
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt
from langchain_openai import ChatOpenAI

from test_agents.agents.worker_base import build_worker_task
from test_agents.config import config
from test_agents.graph.state import SupervisorState, ExecutionPlan, IntentExtraction
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
    """Classify user request intent and extract structured info for relevant requests."""
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

        intent_analysis = None
        if classification == "relevant":
            extracted = assessment.get("extracted")
            if extracted and isinstance(extracted, dict):
                try:
                    validated = IntentExtraction.model_validate(extracted)
                    intent_analysis = validated.model_dump()
                except Exception:
                    intent_analysis = None
    except (json.JSONDecodeError, Exception):
        classification = "ambiguous"
        reason = "意图分类解析失败，默认按模糊请求处理"
        intent_analysis = None

    return {
        "intent_classification": classification,
        "intent_reason": reason,
        "intent_analysis": intent_analysis,
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


def _format_intent_analysis(analysis: dict) -> str:
    """将 intent_analysis 格式化为 planner 可读的文本"""
    parts = []
    if analysis.get("goal"):
        parts.append(f"- 核心意图：{analysis['goal']}")
    if analysis.get("modules"):
        parts.append(f"- 涉及模块：{', '.join(analysis['modules'])}")
    if analysis.get("source_commit") or analysis.get("target_commit"):
        parts.append(f"- Commit 范围：{analysis.get('source_commit', '?')} → {analysis.get('target_commit', '?')}")
    if analysis.get("needs_code_analysis"):
        parts.append("- 需要：代码变更分析")
    if analysis.get("needs_case_review"):
        parts.append("- 需要：测试用例评审")
    if analysis.get("needs_data_analysis"):
        parts.append("- 需要：测试数据分析")
    if analysis.get("test_cases_provided"):
        parts.append("- 用户已提供测试用例")
    if analysis.get("missing_info"):
        parts.append(f"- 缺少信息：{', '.join(analysis['missing_info'])}")
    return "\n".join(parts)


def planner_node(state: SupervisorState) -> dict:
    """Parse user_request and generate ExecutionPlan"""
    llm = get_llm()
    user_request = state.get("user_request", "")
    intent_analysis = state.get("intent_analysis")
    tools_info = ToolRegistry.render_all()

    if intent_analysis:
        analysis_text = _format_intent_analysis(intent_analysis)
    else:
        analysis_text = "(无)"

    prompt = load_prompt(
        "planner",
        user_request=user_request,
        tools_info=tools_info,
        intent_analysis=analysis_text,
    )

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


def _default_output_key(agent: str) -> str:
    """Default output key per agent type."""
    if agent == "code_analyzer":
        return "code_change_report"
    elif agent == "case_reviewer":
        return "review_results"
    elif agent == "data_analyst":
        return "data_insight_report"
    return ""


def dispatch_node(state: SupervisorState) -> dict:
    """Dispatch hub - prepares worker_input and routes via conditional edges."""
    plan = state.get("plan") or {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    current_index = state.get("current_step_index", 0)

    if current_index >= len(steps):
        return {}

    step = steps[current_index]
    task_desc, messages = build_worker_task(step, state)
    output_key = step.get("output_key", "") or _default_output_key(step.get("agent", ""))

    worker_input = {
        "task": task_desc,
        "messages": messages,
        "error": "no",
        "reflection_count": 0,
        "max_reflections": 0,
        "output_key": output_key,
        "result": "",
    }
    return {"worker_input": worker_input}


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


def route_from_dispatch(state: SupervisorState) -> Literal["code_analyzer", "case_reviewer", "data_analyst", "reflect"]:
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
    elif agent == "data_analyst":
        return "data_analyst"
    return "reflect"


def route_from_reflect(state: SupervisorState) -> Literal["planner", "synthesize"]:
    """Route after reflect: replan→planner, complete→synthesize"""
    if state.get("needs_replan") and state.get("plan_iterations", 0) < state.get("max_plan_iterations", 1):
        return "planner"
    return "synthesize"


def route_from_classifier(state: SupervisorState) -> Literal["planner", "reply"]:
    """Route after intent_classifier: relevant→planner, ambiguous/irrelevant→reply"""
    classification = state.get("intent_classification", "")
    if classification == "relevant":
        return "planner"
    return "reply"
