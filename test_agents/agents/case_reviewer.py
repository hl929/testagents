"""用例评审智能体"""

import json
from test_agents.tools.claude_cli import ClaudeCliTool


def case_reviewer_node(state: dict) -> dict:
    """用例评审节点

    1. 读取 code_change_report + test_cases + business_knowledge
    2. 调用 ClaudeCliTool 进行评审
    3. 输出评审结果
    """
    code_change_report = state.get("code_change_report", "")
    test_cases = state.get("test_cases", [])
    business_knowledge = state.get("business_knowledge", "")

    if not code_change_report:
        return {"error": "缺少代码变更报告，请先执行代码分析"}

    if not test_cases:
        return {"review_results": []}

    # 构建用例文本
    cases_text = json.dumps(test_cases, ensure_ascii=False, indent=2)

    # 调用 Claude CLI 评审
    claude_tool = ClaudeCliTool()

    prompt = f"""请基于以下代码变更报告评审测试用例：

## 代码变更报告
{code_change_report}

## 业务知识
{business_knowledge or "无"}

## 待评审用例
{cases_text}

请输出 JSON 格式的评审结果：
```json
[
  {{
    "case_id": "TC001",
    "title": "...",
    "verdict": "pass|fail|needs_improvement",
    "score": 85,
    "issues": ["..."],
    "suggestions": ["..."],
    "coverage_assessment": "..."
  }}
]
```
"""

    review = claude_tool.run({"prompt": prompt})

    if review.startswith("错误:"):
        return {"error": review}

    # 尝试解析 JSON
    try:
        # 提取 JSON 块
        if "```json" in review:
            json_str = review.split("```json")[1].split("```")[0].strip()
        elif "```" in review:
            json_str = review.split("```")[1].split("```")[0].strip()
        else:
            json_str = review

        review_results = json.loads(json_str)
        if not isinstance(review_results, list):
            review_results = [review_results]

        return {"review_results": review_results}

    except json.JSONDecodeError:
        return {
            "review_results": [{
                "case_id": "N/A",
                "title": "解析失败",
                "verdict": "needs_improvement",
                "score": 0,
                "issues": ["评审结果解析失败"],
                "suggestions": [f"原始输出: {review[:500]}"],
            }]
        }
