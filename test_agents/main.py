"""CLI 入口点 - 自然语言输入 + 双模式调度"""

import argparse
import json
import sys

from langgraph.types import Command

from test_agents.config import config
from test_agents.graph.builder import build_graph


_SINGLE_AGENT_KEYWORDS = {
    "code_analyzer": ["分析代码", "代码变更", "code change", "git diff", "代码分析"],
    "case_reviewer": ["评审用例", "测试用例评审", "case review", "用例评审", "评审测试用例"],
}


def is_simple_request(user_request: str) -> str | None:
    """Check if request maps to a single agent. Returns agent name or None."""
    matches = []
    for agent, keywords in _SINGLE_AGENT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in user_request.lower():
                matches.append(agent)
                break

    if len(matches) == 1:
        return matches[0]
    return None


def _build_initial_state(user_request: str) -> dict:
    """Build initial SupervisorState for graph invocation"""
    return {
        "user_request": user_request,
        "targets": [],
        "test_cases": [],
        "business_knowledge": "",
        "plan": None,
        "current_step_index": 0,
        "step_results": [],
        "needs_replan": False,
        "reflection_feedback": None,
        "max_plan_iterations": config.MAX_PLAN_ITERATIONS,
        "plan_iterations": 0,
        "confirm_retry_count": 0,
        "max_confirm_retries": config.MAX_CONFIRM_RETRIES,
        "code_change_report": "",
        "review_results": [],
        "final_answer": None,
        "messages": [],
    }


def run_test_agents(user_request: str) -> dict:
    """运行测试智能体群"""
    app = build_graph()
    thread_config = {"configurable": {"thread_id": "test-agents-session"}}
    initial_state = _build_initial_state(user_request)

    result = app.invoke(initial_state, thread_config)

    # Handle interrupts (confirm_plan)
    while True:
        state = app.get_state(thread_config)
        if not state.next:
            break
        # Graph is paused at confirm_plan
        plan = state.values.get("plan", {})
        _display_plan(plan)
        confirmed = input("\n确认计划？(y/n): ").lower().strip()
        if confirmed == "y":
            app.invoke(Command(resume={"confirmed": True}), thread_config)
        else:
            feedback = input("请输入修改建议: ")
            app.invoke(Command(resume={"confirmed": False, "feedback": feedback}), thread_config)

    # Get final state
    final_state = app.get_state(thread_config)
    return final_state.values


def _display_plan(plan: dict):
    """Display execution plan for user confirmation"""
    if not plan:
        print("（无计划）")
        return
    print(f"\n执行计划: {plan.get('intent', 'N/A')}")
    print("-" * 40)
    for step in plan.get("steps", []):
        print(f"  步骤 {step.get('step_id')}: [{step.get('agent')}] {step.get('description')}")


def main():
    """CLI 主函数"""
    parser = argparse.ArgumentParser(description="测试智能体群 v3")
    parser.add_argument("request", nargs="?", help="自然语言需求描述")
    parser.add_argument("--output", default="text", choices=["json", "text"], help="输出格式")
    args = parser.parse_args()

    if args.request:
        user_request = args.request
    else:
        user_request = input("请输入需求: ")

    result = run_test_agents(user_request)

    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        if result.get("final_answer"):
            print(f"\n{result['final_answer']}")
        else:
            print("\n（未生成最终结果）")


if __name__ == "__main__":
    main()