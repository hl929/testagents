"""代码分析智能体"""

from test_agents.tools.git_diff import GitDiffTool
from test_agents.tools.claude_cli import ClaudeCliTool


def code_analyzer_node(state) -> dict:
    """代码分析节点

    1. 调用 GitDiffTool 提取变更
    2. 将变更内容通过 ClaudeCliTool 传递给 Claude CLI 分析
    3. 返回结构化变更报告
    """
    if hasattr(state, "model_dump"):
        state = state.model_dump()

    module_name = state.get("module_name", "")
    source_commit = state.get("source_commit", "")
    target_commit = state.get("target_commit", "")
    commit_msg = state.get("commit_msg", "")

    if not all([module_name, source_commit, target_commit]):
        return {"error": "缺少必需的参数: module_name, source_commit, target_commit"}

    # 步骤 1: 提取 git diff
    git_tool = GitDiffTool()
    diff_result = git_tool.run({
        "module_name": module_name,
        "source_commit": source_commit,
        "target_commit": target_commit,
    })

    if diff_result.startswith("错误:"):
        return {"error": diff_result}

    # 步骤 2: 调用 Claude CLI 分析
    claude_tool = ClaudeCliTool()

    prompt = f"""请分析以下代码变更，输出结构化报告：

模块：{module_name}
Commit 范围：{source_commit}..{target_commit}
Commit 消息：{commit_msg}

变更内容：
{diff_result}

请输出以下格式的报告：
## 变更概述
...
## 新增/修改/删除的文件
...
## 关键逻辑变更
...
## 影响范围评估
...
"""

    analysis = claude_tool.run({"prompt": prompt})

    if analysis.startswith("错误:"):
        return {"error": analysis}

    return {"code_change_report": analysis}
