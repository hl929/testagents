"""代码分析智能体"""

from test_agents.tools.claude_cli import ClaudeCliTool
from test_agents.prompts.loader import load_prompt


def code_analyzer_node(state) -> dict:
    """代码分析节点

    1. 将模块名、commit 范围等信息通过 ClaudeCliTool 传递给 Claude CLI
    2. Claude CLI 调用 code_analysis_skill，Skill 内部执行 git diff 获取变更
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

    prompt = load_prompt(
        "code_analyzer",
        module_name=module_name,
        source_commit=source_commit,
        target_commit=target_commit,
        commit_msg=commit_msg,
    )

    claude_tool = ClaudeCliTool()
    analysis = claude_tool.run({"prompt": prompt})

    if analysis.startswith("错误:"):
        return {"error": analysis}

    return {"code_change_report": analysis}
