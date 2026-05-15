"""CLI 入口点"""

import argparse
import json
import sys

from test_agents.graph.builder import build_graph
from test_agents.graph.state import TestAgentState


def run_test_agents(
    module_name: str,
    source_commit: str,
    target_commit: str,
    commit_msg: str = "",
    test_cases: str = "",
    business_knowledge: str = "",
) -> dict:
    """运行测试智能体群"""
    # 解析测试用例
    parsed_cases = []
    if test_cases:
        try:
            parsed = json.loads(test_cases)
            if isinstance(parsed, list):
                parsed_cases = parsed
            elif isinstance(parsed, dict):
                parsed_cases = [parsed]
        except json.JSONDecodeError:
            print("警告: 测试用例 JSON 解析失败，将使用空列表", file=sys.stderr)

    # 构建初始状态
    state = TestAgentState(
        module_name=module_name,
        source_commit=source_commit,
        target_commit=target_commit,
        commit_msg=commit_msg,
        test_cases=parsed_cases,
        business_knowledge=business_knowledge,
    )

    # 构建图并运行
    app = build_graph()

    config = {"configurable": {"thread_id": f"{module_name}-{source_commit}"}}
    result = app.invoke(state.model_dump(), config)

    return result


def main():
    """CLI 主函数"""
    parser = argparse.ArgumentParser(description="测试智能体群")
    parser.add_argument("--module", required=True, help="模块名称")
    parser.add_argument("--source", required=True, help="源 commit SHA")
    parser.add_argument("--target", required=True, help="目标 commit SHA")
    parser.add_argument("--msg", default="", help="commit message")
    parser.add_argument("--cases", default="", help="测试用例 JSON 字符串")
    parser.add_argument("--knowledge", default="", help="业务知识")
    parser.add_argument("--output", default="json", choices=["json", "markdown"], help="输出格式")

    args = parser.parse_args()

    result = run_test_agents(
        module_name=args.module,
        source_commit=args.source,
        target_commit=args.target,
        commit_msg=args.msg,
        test_cases=args.cases,
        business_knowledge=args.knowledge,
    )

    # 输出结果
    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("# 测试智能体群执行结果\n")
        print(f"## 代码变更报告\n{result.get('code_change_report', 'N/A')}\n")
        print(f"## 用例评审结果")
        for r in result.get("review_results", []):
            print(f"\n### {r.get('case_id', 'N/A')} - {r.get('title', '')}")
            print(f"- 结论: {r.get('verdict', 'N/A')}")
            print(f"- 得分: {r.get('score', 'N/A')}")


if __name__ == "__main__":
    main()
