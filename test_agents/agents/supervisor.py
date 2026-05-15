"""测试经理 Supervisor - 负责任务调度"""

from typing import Literal


def route_decision(state) -> Literal["analyze", "review", "end"]:
    """根据当前 state 决定下一步路由

    决策逻辑:
    1. 如果 code_change_report 为空 -> 调用代码分析
    2. 如果 test_cases 非空且 review_results 为空 -> 调用用例评审
    3. 其他情况 -> 结束
    """
    if hasattr(state, "model_dump"):
        state = state.model_dump()

    code_report = state.get("code_change_report", "")
    test_cases = state.get("test_cases", [])
    review_results = state.get("review_results", [])
    error = state.get("error", "")

    # 如果有错误，直接结束
    if error:
        return "end"

    # 还没有代码分析报告
    if not code_report:
        return "analyze"

    # 有测试用例需要评审
    if test_cases and not review_results:
        return "review"

    # 所有任务完成或无需评审
    return "end"


def supervisor_node(state) -> dict:
    """Supervisor 节点 - 更新 next_step"""
    next_step = route_decision(state)
    return {"next_step": next_step}
