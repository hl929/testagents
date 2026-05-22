"""CLI 入口点 - 自然语言输入 + 双模式调度"""

import argparse
import json
import sys

from langgraph.types import Command
from langchain_core.messages import HumanMessage

from test_agents.config import config
from test_agents.graph.builder import build_graph
from test_agents.agents.worker_base import WORKER_REGISTRY
from test_agents.graph.state import WorkerState
from test_agents.observability import (
    setup_logging, new_trace, get_trace_id, new_trace_metrics,
    flush_metrics, close_trace_writer, make_run_config,
)

# Initialize once at module load. Idempotent.
setup_logging()


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
        "final_answer": None,
        "messages": [],
        "intent_classification": "",
        "intent_reason": "",
        "intent_analysis": None,
    }


def run_test_agents(user_request: str) -> dict:
    """运行测试智能体群（简单请求直接走 Worker，复杂请求走 Supervisor）"""
    build_graph()
    simple_agent = is_simple_request(user_request)
    if simple_agent:
        return _with_observability(
            lambda: _run_direct_worker(user_request, simple_agent),
            user_request,
            kind="simple",
        )
    return _with_observability(
        lambda: _run_supervisor(user_request),
        user_request,
        kind="supervisor",
    )


def _with_observability(target_func, user_request: str, kind: str) -> dict:
    """Trace lifecycle wrapper (spec §6 + Eng Finding 4.1/4.6).

    Owns:
      - new_trace() / new_trace_metrics() at entry
      - flush_metrics(status=ok|error|aborted) on every exit
      - close_trace_writer() in finally
    """
    trace_id = new_trace(user_request)
    new_trace_metrics(trace_id, user_request)
    status = "ok"
    final_answer = ""
    try:
        result = target_func()
        final_answer = (result.get("final_answer") if isinstance(result, dict) else "") or ""
        # Supervisor path may return without final_answer if confirm_retry
        # limit was hit (Eng Finding 4.6).
        if not final_answer and kind == "supervisor":
            status = "aborted"
        return result
    except BaseException:
        status = "error"
        raise
    finally:
        flush_metrics(trace_id, status=status, final_answer_length=len(final_answer))
        close_trace_writer(trace_id)


def _run_direct_worker(user_request: str, agent_name: str) -> dict:
    """直接调用 Worker 子图，跳过 planner/confirm/reflect/synthesize。"""
    worker_graph = WORKER_REGISTRY.get(agent_name)
    if worker_graph is None:
        raise RuntimeError(f"Worker graph for {agent_name} not found in registry")
    worker_input: WorkerState = {
        "task": user_request,
        "messages": [HumanMessage(content=user_request)],
        "error": "no",
        "reflection_count": 0,
        "max_reflections": 0,
        "output_key": "result",
        "result": "",
    }
    # Eng Finding 1.3: callback must fire on simple-worker path too.
    result = worker_graph.invoke(worker_input, make_run_config(thread_id=f"direct-{agent_name}"))
    output_text = result.get("result", "")
    if not output_text:
        for msg in reversed(result.get("messages", [])):
            if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                output_text = msg.content
                break
    output_key = "code_change_report" if agent_name == "code_analyzer" else "review_results"
    return {
        "user_request": user_request,
        "outputs": {output_key: output_text},
        "final_answer": output_text,
        "step_results": [
            {"step_id": 1, "agent": agent_name, "status": "success", "output_key": output_key}
        ],
    }


def _run_supervisor(user_request: str) -> dict:
    """走完整的 Supervisor 主图。"""
    app = build_graph()
    thread_config = make_run_config(thread_id="test-agents-session")
    initial_state = _build_initial_state(user_request)
    result = app.invoke(initial_state, thread_config)
    while True:
        state = app.get_state(thread_config)
        if not state.next:
            break
        plan = state.values.get("plan", {})
        _display_plan(plan, file=sys.stderr)
        confirmed = input("\n确认计划？(y/n): ").lower().strip()
        if confirmed == "y":
            app.invoke(Command(resume={"confirmed": True}), thread_config)
        else:
            feedback = input("请输入修改建议: ")
            app.invoke(Command(resume={"confirmed": False, "feedback": feedback}), thread_config)
    final_state = app.get_state(thread_config)
    return final_state.values


def _display_plan(plan: dict, file=None):
    """Display execution plan for user confirmation"""
    if file is None:
        file = sys.stdout
    if not plan:
        print("（无计划）", file=file)
        return
    print(f"\n执行计划: {plan.get('intent', 'N/A')}", file=file)
    print("-" * 40, file=file)
    for step in plan.get("steps", []):
        print(f"  步骤 {step.get('step_id')}: [{step.get('agent')}] {step.get('description')}", file=file)


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
        # ensure_ascii=True 避免 Windows GBK 终端编码失败
        print(json.dumps(result, ensure_ascii=True, indent=2, default=str))
    else:
        if result.get("final_answer"):
            print(f"\n{result['final_answer']}")
        else:
            print("\n（未生成最终结果）")


if __name__ == "__main__":
    main()