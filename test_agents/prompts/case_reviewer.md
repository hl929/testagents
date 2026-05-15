请基于以下代码变更报告评审测试用例：

## 代码变更报告
{code_change_report}

## 业务知识
{business_knowledge}

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
